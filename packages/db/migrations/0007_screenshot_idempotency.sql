DELETE FROM screenshots
WHERE rowid NOT IN (
  SELECT MAX(rowid)
  FROM screenshots
  GROUP BY application_run_id, screenshot_id
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_screenshots_run_screenshot_id
ON screenshots(application_run_id, screenshot_id);
