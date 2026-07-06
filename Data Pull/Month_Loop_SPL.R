# install.packages(c("aws.s3", "httr", "jsonlite", "purrr"))
library(httr)
library(jsonlite)
library(purrr)
library(aws.s3)

Sys.setenv(
  AWS_ACCESS_KEY_ID = Sys.getenv("AWS_ACCESS_KEY_ID"),
  AWS_SECRET_ACCESS_KEY = Sys.getenv("AWS_SECRET_ACCESS_KEY"),
)
Sys.unsetenv("AWS_DEFAULT_REGION")
r2_endpoint <- "dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com"
bucket <- "spl-checkouts"

stopifnot(bucket_exists(bucket = bucket, region = "", base_url = r2_endpoint, use_https = TRUE))
cat("Bucket connection OK.\n")
 
# ---- Config -------------------------------------------------------------
socrata_url <- "https://data.seattle.gov/resource/tmmm-ytt6.json"
start_year  <- 2006
 
end_date  <- Sys.Date()
end_year  <- as.integer(format(end_date, "%Y"))
end_month <- as.integer(format(end_date, "%m"))
 
CHUNK_SIZE  <- 1000000L
MAX_RETRIES <- 5
 
# ---- Helpers with retry/backoff -----------------------------------------
 
# Generic retry wrapper: retries `expr` (a function with no args) on
# failure or on an unexpected/malformed response, with exponential backoff.
with_retry <- function(fn, description, max_retries = MAX_RETRIES) {
  for (attempt in seq_len(max_retries)) {
    result <- tryCatch(fn(), error = function(e) {
      cat(sprintf("  [%s] attempt %d failed: %s\n", description, attempt, conditionMessage(e)))
      NULL
    })
    if (!is.null(result)) return(result)
    if (attempt < max_retries) {
      wait <- 2^attempt
      cat(sprintf("  Retrying %s in %ds...\n", description, wait))
      Sys.sleep(wait)
    }
  }
  stop(sprintf("Failed '%s' after %d attempts", description, max_retries))
}
 
get_count <- function(where_clause) {
  with_retry(function() {
    resp <- GET(socrata_url, query = list(
      "$select" = "COUNT(*) AS total_count",
      "$where"  = where_clause
    ))
    if (status_code(resp) != 200) stop(sprintf("HTTP %d", status_code(resp)))
 
    parsed <- resp |> content("text", encoding = "UTF-8") |> fromJSON()
 
    if (!is.data.frame(parsed) || !"total_count" %in% names(parsed) || nrow(parsed) != 1) {
      stop("unexpected count response shape")
    }
    val <- suppressWarnings(as.numeric(parsed$total_count))
    if (is.na(val)) stop("count did not parse as numeric")
    val
  }, description = paste("count:", where_clause))
}
 
fetch_data <- function(where_clause, offset) {
  with_retry(function() {
    resp <- GET(socrata_url, query = list(
      "$where"  = where_clause,
      "$limit"  = CHUNK_SIZE,
      "$offset" = as.integer(offset)
    ))
    if (status_code(resp) != 200) stop(sprintf("HTTP %d", status_code(resp)))
    resp |> content("text", encoding = "UTF-8") |> fromJSON()
  }, description = sprintf("fetch offset=%d: %s", offset, where_clause))
}
 
upload_month <- function(df, year, month) {
  outfile <- tempfile(fileext = ".csv")
  on.exit(unlink(outfile), add = TRUE)

  write.csv(df, outfile, row.names = FALSE)
  cat(sprintf("  File size: %.1f MB\n", file.size(outfile) / 1e6))

  with_retry(function() {
    ok <- put_object(
      file     = outfile,
      object   = sprintf("monthly/checkouts_%d_%02d.csv", year, month),
      bucket   = bucket,
      region   = "",
      base_url = r2_endpoint,
      use_https = TRUE
    )

    resp <- attr(ok, "response")
    status <- if (!is.null(resp)) httr::status_code(resp) else NA

    if (isTRUE(ok) || (!is.na(status) && status == 200)) {
      return(TRUE)
    }

    cat("  put_object failed. Status:", status, "\n")
    str(ok)
    stop("put_object failed")
  }, description = sprintf("upload %d-%02d", year, month))
}




 
# ---- Resume logic ---------------------------------------------------------
# Rather than tracking a separate local folder, check what's already in the
# bucket and skip any year/month that's already uploaded. This makes the
# script safely re-runnable after any failure -- just run it again.
get_completed_months <- function() {
  existing <- tryCatch(
    get_bucket_df(bucket = bucket, prefix = "monthly/", region = "", base_url = r2_endpoint, use_https = TRUE),
    error = function(e) NULL
  )
  if (is.null(existing) || nrow(existing) == 0) return(character(0))
 
  # keys look like monthly/checkouts_2006_01.csv
  keys <- existing$Key
  m <- regmatches(keys, regexec("checkouts_(\\d{4})_(\\d{2})\\.csv$", keys))
  done <- vapply(m, function(x) if (length(x) == 3) paste0(x[2], "-", x[3]) else NA_character_, character(1))
  done[!is.na(done)]
}
 
completed <- get_completed_months()
cat(sprintf("Found %d months already uploaded to bucket.\n", length(completed)))
 
# ---- Main loop -------------------------------------------------------------
for (year in start_year:end_year) {
  for (month in 1:12) {
    if (year == end_year && month > end_month) break
 
    key <- sprintf("%d-%02d", year, month)
    if (key %in% completed) {
      cat(sprintf("Skipping %s (already uploaded)\n", key))
      next
    }
 
    cat(sprintf("Processing %s\n", key))
 
    where_clause <- sprintf("checkoutyear = %d AND checkoutmonth = %d", year, month)
 
    count_data <- get_count(where_clause)
 
    if (count_data == 0) {
      cat(sprintf("  No records for %s, skipping.\n", key))
      next
    }
 
    n_chunks <- ceiling(count_data / CHUNK_SIZE)
    results <- vector("list", length = n_chunks)
 
    for (i in seq_len(n_chunks)) {
      offset <- (i - 1) * CHUNK_SIZE
      results[[i]] <- fetch_data(where_clause, offset)
      Sys.sleep(1)  # be polite to the Socrata API between chunk requests
    }
 
    month_results <- purrr::list_rbind(results)
 
    upload_month(month_results, year, month)
    cat(sprintf("  Uploaded %s (%d rows)\n", key, nrow(month_results)))
 
    rm(results, month_results)
    gc()
 
    Sys.sleep(1)  # be polite to the Socrata API between months
  }
}
 
cat("Done.\n")
