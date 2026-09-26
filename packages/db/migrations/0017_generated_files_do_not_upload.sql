-- Marks a generated file the worker must never attach to an application, such
-- as a second resume kept only for the user to compare. review_only cannot do
-- this job: a review_only cover letter is still meant to be uploaded.
ALTER TABLE generated_files ADD COLUMN do_not_upload INTEGER NOT NULL DEFAULT 0;
