# Interview Notes

## Why FastAPI?

FastAPI is a lightweight Python framework with clear routing, request validation through Pydantic, and generated OpenAPI/Swagger documentation. It keeps this project focused on API and backend fundamentals.

## Why background processing?

PDF generation can take time, especially for a large batch. The API validates and saves the request, returns `202 Accepted`, and lets the client check progress while the work runs.

## Why not create every PDF inside the HTTP request?

The request would stay open while all files are rendered. That increases timeouts and ties up web workers. A background task releases the request quickly and allows progress to be stored between recipients.

## Why use a database?

The database preserves job state, counts, certificate metadata, and failures after the request ends. It also gives the API a reliable way to answer status and listing requests.

## Why separate `generation_jobs` and `certificates`?

One job represents the batch and its aggregate counts. Each certificate row represents one recipient and one independent result. This avoids duplicating job-level information on every row and makes partial success visible.

## What happens if one certificate fails?

The processor catches the error around that recipient, records a failed status and safe error summary, updates job counts, then proceeds to the next person. The final job is `COMPLETED_WITH_ERRORS` if at least one certificate failed.

## How is progress tracked?

After each recipient, the processor increments completed and success/failure counts. The API calculates `completed_count / total_count * 100`; it does not store a second value that could become stale.

## How would you handle 100,000 recipients?

I would move work out of the API process into a durable queue, split batches into bounded chunks, run multiple workers, and monitor queue delay and failure rates. I would also limit request size, use bulk database inserts where helpful, and store PDFs in object storage instead of a local disk.

## What are the limitations of FastAPI `BackgroundTasks`?

It runs work in the same process as the API. A process crash or restart can interrupt the job, there is no durable queue or built-in retry policy, and it does not scale independently from web traffic. It is simple for a local assignment, not a delivery guarantee.

## How could Celery or RQ replace it?

Keep the job service and the API payload/response contract. Replace the line that schedules the in-process task with a queue adapter that sends the job ID. A worker calls the same job processor using its own database sessions.

## How would Redis help?

Redis can back a task queue and hold short-lived coordination or retry data. The database should remain the durable record of job and certificate outcomes; Redis availability should not be the only place that progress exists.

## How would you scale certificate generation?

Run several independent workers consuming queued job IDs or recipient chunks. Make each unit idempotent, claim it transactionally, store files in shared object storage, and size worker concurrency based on CPU and PDF throughput.

## How would you prevent duplicate processing?

This version atomically changes a job from `PENDING` to `PROCESSING`; only one worker can update a pending row and claim it. A production queue worker should also use idempotency keys, leases, and guarded certificate state changes so retries do not create duplicate outputs.

## How would you store certificates in AWS S3?

Create an object key from trusted UUIDs, upload the PDF, store the object key in the database, and return a short-lived signed URL after checking the caller's authorization. Never build an object key directly from a recipient name.

## Why store file paths instead of PDF bytes in the database?

PDFs can be much larger than their metadata. Keeping them in filesystem or object storage makes database backups and queries smaller while the database retains status and a reference to the file.

## What if the application crashes halfway through a job?

Some certificates may already be complete, while the job remains `PROCESSING`. In this assignment the in-process worker has no crash recovery. A production version would record a lease/heartbeat, detect stale jobs, and requeue only certificates that are not complete.

## How would retries work?

Store attempt count and last error, classify transient versus permanent errors, and retry transient failures with a capped exponential backoff. Each attempt should write to a temporary file and atomically publish the final object so retrying cannot expose a partial PDF.

## How would you add authentication?

Use OAuth2/JWT or an identity provider, associate jobs with an account, and verify ownership before returning status, recipient details, or downloads. Avoid logging credentials or tokens.

## How would you rate-limit the API?

Apply per-account limits at an API gateway or middleware, and add a maximum recipient count and request body size. For sustained traffic, queue admission should also consider worker capacity.

## How would you monitor failed jobs?

Emit structured job and certificate logs with IDs and outcome counts, expose metrics for duration, queue delay, and failure rate, and alert on stale processing jobs or repeated failures. Keep recipient PII out of logs.

## Current trade-offs

The project uses in-process background tasks and local storage so a developer can run it without infrastructure. Its API and service boundary leave room for a durable queue, PostgreSQL, and object storage when delivery guarantees or multi-instance scaling are needed.
