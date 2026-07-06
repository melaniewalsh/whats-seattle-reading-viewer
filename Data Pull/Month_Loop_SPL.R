library(httr)
library(jsonlite)
library(purrr)

# Set the base URL for the Library checkout data
base_url <- "https://data.seattle.gov/resource/tmmm-ytt6.json"

# Directory to save monthly files
output_dir <- "monthly_checkouts"
dir.create(output_dir, showWarnings = FALSE)

# Function to fetch JSON data in chunks of 1,000,000 records
fetch_data <- function(where_clause, offset) {
  query_params <- list(
    "$where" = where_clause,
    "$limit" = as.integer(1000000),
    "$offset" = offset
  )

  GET(base_url, query = query_params) |>
    content("text", encoding = "UTF-8") |>
    fromJSON()
}

start_year <- 2006
end_date <- Sys.Date()
end_year <- as.integer(format(end_date, "%Y"))
end_month <- as.integer(format(end_date, "%m"))

for (year in start_year:end_year) {
  for (month in 1:12) {

    if (year == end_year && month > end_month) {
      break
    }

    cat(sprintf("Processing %d-%02d\n", year, month))

    where_clause <- sprintf(
      "checkoutyear = %d AND checkoutmonth = %d",
      year,
      month
    )

    count_params <- list(
      "$select" = "COUNT(*) AS total_count",
      "$where" = where_clause
    )

    count_data <- GET(base_url, query = count_params) |>
      content("text", encoding = "UTF-8") |>
      fromJSON() |>
      as.numeric()

    if (count_data == 0) {
      next
    }

    results <- vector("list", length = ceiling(count_data / 1000000))

    for (i in seq_along(results)) {
      offset <- (i - 1) * 1000000
      results[[i]] <- fetch_data(where_clause, as.integer(offset))
    }

    month_results <- purrr::list_rbind(results)

    outfile <- file.path(
      output_dir,
      sprintf("checkouts_%d_%02d.csv", year, month)
    )

    write.csv(month_results, outfile, row.names = FALSE)

    # Immediately free memory
    rm(results, month_results)
    gc()
  }
}