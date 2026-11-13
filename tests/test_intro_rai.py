"""Offline SDK checks. These do not claim live RAI correctness or performance."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from relationalai.util import schema
from relationalai.semantics.backends.legacy_executor import LegacyExecutor
from pe_deal_graph.intro_rai import IntroductionModel, SOURCE, BASE

SCHEMAS = {
    BASE+'.PERSON': dict(ID='String', NAME='String'),
    SOURCE+'.PERSON_LABEL': dict(ID='String', NAME='String'),
    SOURCE+'.TEAM_MEMBERS': dict(PERSON_ID='String'),
    BASE+'.KNOWS': dict(P1='String', P2='String', STRENGTH='Float', EVIDENCE='String'),
    SOURCE+'.ROLE_HISTORY': dict(ROLE_ID='String', PERSON_ID='String', ORG_ID='String',
                                ORG_NAME='String', START_DATE='Date', END_DATE='Date'),
    SOURCE+'.DEAL_PARTY': dict(TRANSACTION_ID='String', CLOSE_DATE='Date', LEAD_PERSON_ID='String', PARTY_ROLE='String'),
    SOURCE+'.CRM_INTERACTION': dict(INTERACTION_ID='String', OUR_PERSON_ID='String',
                                    COUNTERPARTY_PERSON_ID='String', INTERACTION_DATE='Date', SENTIMENT='String'),
}


@pytest.fixture(autouse=True)
def no_network():
    def blocked(*a, **kw):
        raise AssertionError('Offline checks must not contact Snowflake or a reasoner')
    with patch('socket.socket.connect', blocked), patch.object(schema, 'CACHE', dict(SCHEMAS)), \
         patch.object(schema, '_save_cache', blocked):
        yield


@pytest.mark.parametrize('source,hops,threshold', [('', 12, 0.), ('P19079', 5, .75), ('P19079', 0, 1.)])
def test_routes_translate_to_logic(source, hops, threshold):
    model = IntroductionModel(min_strength=threshold)
    assert not model.model.config.deployment_enabled
    query = model.route_query('P19079', source, hops)
    executor = LegacyExecutor(model.model)
    executor._translate_model(model.model.to_metamodel(), None, 'lqp', [])
    executor._translate_query(query.to_metamodel(), 'lqp', [])


def test_enriched_community_graph_translates():
    from relationalai.semantics import Integer, Float
    model = IntroductionModel()
    labels, scores, sampled = model.communities()
    p, c, s = model.person.ref(), Integer.ref(), Float.ref()
    query = model.model.where(labels(p, c), scores(p, s)).select(p.id, c, s)
    executor = LegacyExecutor(model.model)
    executor._translate_model(model.model.to_metamodel(), None, 'lqp', [])
    executor._translate_query(query.to_metamodel(), 'lqp', [])


@pytest.mark.parametrize('threshold', [-.1, 1.1, float('nan'), float('inf'), True])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError):
        IntroductionModel(min_strength=threshold)


@pytest.mark.parametrize('target,source,limit', [('', '', 2), ('x', None, 2), ('x', '', -1), ('x', '', 13), ('x', '', True)])
def test_invalid_request(target, source, limit):
    with pytest.raises(ValueError):
        IntroductionModel().route_query(target, source, limit)


def test_suspended_engine_stops_before_queries():
    model = IntroductionModel()
    session = SimpleNamespace(sql=lambda *a, **kw: SimpleNamespace(collect=lambda: [('SUSPENDED',)]))
    with patch.object(type(model.model.config), 'get_session', return_value=session):
        with pytest.raises(RuntimeError, match='no engine changes'):
            model.routes('P19079')


def test_native_agent_handoff_preserves_attribute_tools_and_input():
    import copy
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    from intro_test_agent import native_rai_specification
    old = {'instructions': {'response': 'Keep concise'},
           'tools': [{'tool_spec': {'name': n}} for n in ['intro_lookup', 'find_people', 'person_contacts']],
           'tool_resources': {n: {'identifier': n} for n in ['intro_lookup', 'find_people', 'person_contacts']}}
    before = copy.deepcopy(old)
    native = {'tools': [{'tool_spec': {'name': 'RAI_QUERY_MODEL'}}],
              'tool_resources': {'RAI_QUERY_MODEL': {'identifier': 'test.PE_NATIVE_RAI_QUERY_MODEL'}}}
    result = native_rai_specification(old, native)
    assert old == before
    assert set(result['tool_resources']) == {'find_people', 'person_contacts', 'RAI_QUERY_MODEL'}
    assert result['tool_resources']['find_people'] == old['tool_resources']['find_people']
    assert result['instructions']['response'] == 'Keep concise'
    assert 'intro_lookup' not in result['instructions']['orchestration']
    assert 'not been refreshed' in result['instructions']['orchestration']
