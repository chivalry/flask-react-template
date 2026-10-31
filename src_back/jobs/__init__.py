"""Scheduled jobs: modules that ``python -m src_back.jobs.<name>`` runs once.

A job's ``main()`` builds the app with ``create_app()``, or takes one from a test, does
its work inside one application context, commits, prints one line saying what it did,
and returns the exit status. ``scripts/systemd/job@.service`` runs a job in the backend
container and its timer schedules it; ``ai/project.md`` describes both, and
:mod:`src_back.jobs.example` is the module to copy.
"""
