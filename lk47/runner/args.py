import argparse

# run.py's own defaults with the action set changed
MAX_STEPS = 50


def harness_namespace(result_dir: str) -> argparse.Namespace:
    return argparse.Namespace(
        action_set_tag="playwright",
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_width=1280,
        viewport_height=720,
        max_steps=MAX_STEPS,
        parsing_failure_th=3,
        repeating_action_failure_th=3,
        sleep_after_execution=1.5,
        render=False,
        render_screenshot=True,
        save_trace_enabled=True,
        slow_mo=0,
        result_dir=result_dir,
    )
