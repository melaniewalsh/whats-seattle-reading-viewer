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

# Determine the previous month
today <- Sys.Date()
prev_month_date <- seq(today, length = 2, by = "-1 month")[2]

year <- as.integer(format(prev_month_date, "%Y"))
month <- as.integer(format(prev_month_date, "%m"))

cat(sprintf("Processing %d-%02d\n", year, month))

# Create WHERE clause
where_clause <- sprintf(
  "checkoutyear = %d AND checkoutmonth = %d",
  year,
  month
)

# Get record count
count_params <- list(
  "$select" = "COUNT(*) AS total_count",
  "$where" = where_clause
)

count_data <- GET(base_url, query = count_params) |>
  content("text", encoding = "UTF-8") |>
  fromJSON() |>
  as.numeric()

if (count_data == 0) {
  stop("No records found for the previous month.")
}

# Download all chunks
results <- vector("list", length = ceiling(count_data / 1000000))

for (i in seq_along(results)) {
  offset <- (i - 1) * 1000000
  results[[i]] <- fetch_data(where_clause, as.integer(offset))
}

# Combine chunks
month_results <- purrr::list_rbind(results)

# Write CSV
outfile <- file.path(
  output_dir,
  sprintf("checkouts_%d_%02d.csv", year, month)
)

write.csv(month_results, outfile, row.names = FALSE)

# Free memory
rm(results, month_results)
gc()

cat(sprintf("Finished writing %s\n", outfile))