"""Data import: read CSV/Excel files, profile and validate them, clean them, and store them.

Flow: ``readers.read_file`` → ``profiling.profile`` → ``validation.validate`` →
``preprocess.clean`` → ``store.save_import``. The UI only collects choices and shows results.
"""
