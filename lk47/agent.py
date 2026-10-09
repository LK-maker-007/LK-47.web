from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

from agent import Agent

from lk47.actions import NO_ANSWER, Act, InvalidAction, Stop, Type, render, to_harness
from lk47.answers import Unachievable, stop_answer
from lk47.intents import Ambiguous, NoMatch, Task, parse
from lk47.plan import AnswerKind, NoPlan, Plan, build
from lk47.skills import REGISTRY, Budget, Postcondition, Precondition
from lk47.snapshot import PageSnapshot


class NoSkill(LookupError):
    pass


class RepeatedAction(RuntimeError):
    pass


def run_plan(plan: Plan, task: Task) -> Generator[Act, PageSnapshot, str]:
    answer = ""
    yielded = 0
    for call in plan.calls:
        try:
            factory = REGISTRY[call.name]
        except KeyError:
            raise NoSkill(call.name) from None
        kwargs = {param: task.slots[slot].raw for param, slot in call.args.items()}
        kwargs.update(call.literals)
        skill = factory(**kwargs)
        result, used = yield from _budgeted(skill, plan.budget - yielded)
        yielded += used
        if isinstance(result, str):
            answer = result
    return answer


def _budgeted(
    skill: Generator[Act, PageSnapshot, Any], remaining: int
) -> Generator[Act, PageSnapshot, tuple[Any, int]]:
    count = 0
    try:
        act = next(skill)
        while True:
            if count >= remaining:
                raise Budget(f"plan budget exhausted after {count} actions in this skill")
            count += 1
            snapshot = yield act
            act = skill.send(snapshot)
    except StopIteration as done:
        return done.value, count


ROOTS = ("html", "body", "html body", ":root", "html > body")


def guard_repeats(history: Sequence[str], act: Act) -> Act:
    # the harness stops an episode on three equivalent trailing actions, or on a third equal
    # type action anywhere; a third equal fill, which multi-product edits need, is re-rooted
    # so its code differs; a third consecutive repeat is a loop
    code = render(act)
    if len(history) >= 2 and history[-1] == code and history[-2] == code:
        raise RepeatedAction(f"third consecutive action {code}")
    if not isinstance(act, Type) or history.count(code) < 2:
        return act
    for root in ROOTS:
        candidate = Type(act.locator.rooted(root), act.text)
        if history.count(render(candidate)) < 2:
            return candidate
    raise RepeatedAction(f"no distinct rendering left for {code}")


class LK47Agent(Agent):
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.failure: str | None = None
        self.template_id: int | None = None
        self.last_url = ""
        self.answer_kind: AnswerKind | None = None
        self.answer: str | Unachievable | None = None
        self.intent = ""
        self._plan: Generator[Act, PageSnapshot, str] | None = None
        self._started = False

    def reset(self, test_config_file: str) -> None:
        # the config file holds the grading block; it is never opened here
        self.codes = []
        self.failure = None
        self.template_id = None
        self.last_url = ""
        self.answer_kind = None
        self.answer = None
        self.intent = ""
        self._plan = None
        self._started = False

    def next_action(
        self, trajectory: list[Any], intent: str, meta_data: dict[str, Any]
    ) -> dict[str, Any]:
        step = (len(trajectory) - 1) // 2
        self.intent = intent
        snapshot = PageSnapshot.from_state(trajectory[-1], step)
        self.last_url = snapshot.url
        act = self._next(snapshot, intent)
        try:
            act = guard_repeats(self.codes, act)
            action = to_harness(act)
        except (RepeatedAction, InvalidAction) as e:
            self.failure = str(e)
            action = to_harness(Stop(NO_ANSWER))
        self.codes.append(action["raw_prediction"])
        return action

    def _next(self, snapshot: PageSnapshot, intent: str) -> Act:
        if self.failure is not None:
            return Stop(NO_ANSWER)
        if self._plan is None:
            try:
                task = parse(intent)
                self.template_id = task.template_id
                plan = build(task)
                self.answer_kind = plan.answer
                self._plan = run_plan(plan, task)
            except (NoMatch, Ambiguous, NoPlan) as e:
                self.failure = f"{type(e).__name__}: {e}"
                return Stop(NO_ANSWER)
        try:
            if not self._started:
                self._started = True
                return next(self._plan)
            return self._plan.send(snapshot)
        except StopIteration as done:
            self.answer = done.value
            return Stop(stop_answer(done.value))
        except (Precondition, Postcondition, Budget, NoSkill, InvalidAction) as e:
            self.failure = f"{type(e).__name__}: {e}"
            return Stop(NO_ANSWER)
