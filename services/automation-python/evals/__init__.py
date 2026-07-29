"""Golden dataset and runner for the generated-text stages.

The graders live in `applyocalypse_automation.evals` because the app may want to
call them at runtime. The dataset lives here, outside the shipped package, so it
never ends up inside the PyInstaller bundle.
"""
