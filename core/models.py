# No tables in core. This file exists so Django sends core's post_migrate signal
# (it skips apps without a models module), which core/apps.py uses to switch on RLS.
