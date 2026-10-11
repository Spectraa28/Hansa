"""Conversation contract checks use synthetic outputs, never Swarm or paid models."""
import json

import pytest

from app.config import BACKEND
from app.contracts.schemas import ContractInput, missing_requirements
from app.runner.baseline import score_task
from scripts.prove_airline_conversations import stage_cost


def test_six_airline_conversations_score_executed_sequence_and_outcome():
    raw = json.loads((BACKEND / 'examples/contracts/swarm_airline.json').read_text())
    content = ContractInput.model_validate({**raw, 'configuration_revision': 'a' * 32}).model_dump()
    assert len(content['tasks']) == 6 and not missing_requirements(content)
    for task in content['tasks']:
        assert len(task['input']['user_turns']) >= 2
        rules = {rule['pointer']: rule for rule in task['required_fields']}
        output = {'function_sequence': rules['/function_sequence']['exact_value'], 'messages': [],
                  'resolution': {'action': rules['/resolution/action']['exact_value'],
                                 'result': rules['/resolution/result']['exact_value'] or 'Escalating to agent: assistance needed',
                                 'closed': rules['/resolution/closed']['exact_value']}}
        assert score_task(output, task, content)['automatic_passed']
        assert score_task(output, task, content)['status'] == 'needs_review'
        output['function_sequence'] = list(reversed(output['function_sequence']))
        assert not score_task(output, task, content)['automatic_passed']
        output['function_sequence'] = rules['/function_sequence']['exact_value']
        output['resolution']['closed'] = not rules['/resolution/closed']['exact_value']
        assert not score_task(output, task, content)['automatic_passed']


def test_pipeline_cost_includes_agent_smoke_and_each_baseline_repetition():
    report = {'result': {'agent_usage': {'estimated_cost_usd': 0.1, 'unknown_cost_calls': 0},
                         'target_usage': {'estimated_cost_usd': 0.2, 'unknown_cost_calls': 0}}}
    assert stage_cost('onboarding', report) == pytest.approx(0.3)
    baseline = {'tasks': [{'runs': [{'model_calls': 1, 'cost_usd': 0.1, 'unknown_cost_calls': 0}, {'model_calls': 1, 'cost_usd': 0.2, 'unknown_cost_calls': 0}]}]}
    assert stage_cost('baseline', baseline) == pytest.approx(0.3)
    baseline['tasks'][0]['runs'][0]['unknown_cost_calls'] = 1
    with pytest.raises(ValueError, match='Unknown'):
        stage_cost('baseline', baseline)
    report['result']['target_usage']['unknown_cost_calls'] = 1
    with pytest.raises(ValueError, match='Unknown'):
        stage_cost('onboarding', report)
