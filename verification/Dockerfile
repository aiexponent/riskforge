# Image for verification/run.sh: Python plus the system libraries WeasyPrint needs
# for PDF export, as the RiskForge README lists them. Runs as a non-root user.
# Official python image, mirrored on Amazon ECR Public; pinned by index digest.
FROM public.ecr.aws/docker/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
       shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 verifier
USER verifier
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
