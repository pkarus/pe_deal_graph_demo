"""Dedicated Cortex agent over validated, persisted PE results. No graph execution.

Commands: prepare (offline), deploy, update-agent, use-target-outputs, test, status, chat 'question'.
Deploy creates the agent/tool; update-lookup replaces this tool and updates this agent only.
It refuses to overwrite an existing object. Credentials come from raiconfig.yaml.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
from pe_deal_graph import settings as _cfg  # noqa: E402  (database/schema/role/engine names)
DB = f'{_cfg.DATABASE}'
SCHEMA = f'{_cfg.BASE_SCHEMA}_COMMUNITY'
BASE = f'{DB}.{SCHEMA}'
DISTANCE = f'{DB}.{_cfg.BASE_SCHEMA}_DEPLOY'
SOURCE = DISTANCE + '_SRC'
TARGET_OUTPUT = f'{DB}.{_cfg.BASE_SCHEMA}_TARGETS'
AGENT = BASE + '.PE_GRAPH_ASSISTANT'
PROCEDURE = BASE + '.PE_GRAPH_LOOKUP'
SIGNATURE = '(VARCHAR,VARCHAR,VARCHAR,VARCHAR,VARCHAR,NUMBER)'
SAVED = ROOT / _cfg.AGENT_COMMUNITY_EVIDENCE  # set agent_community_evidence in pe_settings.yaml
REPORT = ROOT / 'artifacts/pe_cortex_agent.json'


def resolve_entity(rows, text, id_key='person_id', name_key='name'):
    """Resolve a unique ID/name; return ambiguity instead of selecting a guess."""
    text = text.strip().casefold()
    exact = [r for r in rows if text in (str(r[id_key]).casefold(), r[name_key].casefold())]
    matches = exact or [r for r in rows if text in r[name_key].casefold()]
    if len(matches) != 1:
        return None, {'status': 'AMBIGUOUS' if matches else 'NOT_FOUND',
                      'query': text, 'matches': matches[:15], 'match_count': len(matches)}
    return matches[0], None


def reconstruct_paths(people, distances, edges, source_id, target_id, limit=3):
    """Reconstruct shortest routes along stored increasing-distance edges.

    No distances or community scores are recomputed. Equal-length routes are
    ranked by the product of edge strengths, then by route IDs. This is a
    heuristic model score, not an introduction-success probability.
    """
    names = {p['person_id']: p['name'] for p in people}
    details = {p['person_id']: {k: p[k] for k in ('person_id','name','role_history','current_roles') if k in p} for p in people}
    hops = {r['target_id']: r['hops'] for r in distances if r['source_id'] == source_id}
    distance = hops.get(target_id)
    if distance is None:
        return {'shortest_route_count': 0, 'routes': [], 'routes_truncated': False,
                'all_two_hop_intermediaries': []}
    if hops.get(source_id) != 0 or distance < 0 or int(distance) != distance:
        raise ValueError('Stored source distances are inconsistent')
    adjacency, strengths, evidence = {}, {}, {}
    for edge in edges:
        a, b = edge['p1'], edge['p2']
        if edge['strength'] < 0:
            continue
        if a not in names or b not in names:
            raise ValueError('Persisted edge endpoint missing from people')
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
        strengths[tuple(sorted((a, b)))] = edge['strength']
        evidence[tuple(sorted((a, b)))] = {k: edge.get(k) for k in ('evidence','evidence_count')}
    predecessors = {node: sorted(n for n in adjacency.get(node, ())
                                if hops.get(n) == depth - 1)
                    for node, depth in hops.items() if 0 < depth <= distance}
    counts = {source_id: 1}
    for node in sorted(predecessors, key=lambda n: (hops[n], n)):
        counts[node] = sum(counts.get(n, 0) for n in predecessors[node])
    count = counts.get(target_id, 0)
    if count == 0:
        raise ValueError('Stored distance has no supporting route in persisted edges')
    # Top-k dynamic programming over the stored shortest-distance DAG.
    # Keep lexical prefixes too: a later zero-strength edge makes all scores tie.
    prefixes = {source_id: [(1.0, (source_id,))]}
    for node in sorted(predecessors, key=lambda n: (hops[n], n)):
        candidates = [(score * strengths[tuple(sorted((parent,node)))], path + (node,))
                      for parent in predecessors[node] for score,path in prefixes.get(parent, [])]
        best = sorted(candidates, key=lambda r: (-r[0],r[1]))[:limit]
        lexical = sorted(candidates, key=lambda r: r[1])[:limit]
        prefixes[node] = list({path: (score,path) for score,path in best + lexical}.values())
    paths = []
    for score,path in sorted(prefixes[target_id], key=lambda r: (-r[0],r[1]))[:limit]:
        paths.append({'people': [details[n] for n in path], 'route_strength': score,
                      'edges': [dict(from_id=a, to_id=b,
                                     strength=strengths[tuple(sorted((a,b)))],
                                     **evidence[tuple(sorted((a,b)))])
                                for a,b in zip(path,path[1:])]})
    intermediaries = ([{'person_id': n, 'name': names[n]} for n in predecessors[target_id]
                      if counts.get(n, 0)] if distance == 2 else [])
    return {'shortest_route_count': count, 'routes': paths,
            'routes_truncated': count > len(paths), 'all_two_hop_intermediaries': intermediaries}


def answer_lookup(people, distances, seeds, targets, companies, operation,
                  person='', target_company='', source_person='', community_id='', top_n=3, edges=None):
    """Filter stored rows and rank stored scores; never calculate graph algorithms."""
    if operation not in ('catalog', 'distance', 'paths', 'community', 'connectors'):
        return {'status': 'UNSUPPORTED_OPERATION'}
    if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= 10:
        return {'status': 'INVALID_TOP_N', 'allowed': '1 through 10'}
    if sum(bool(x) for x in (person, target_company, community_id)) > 1:
        return {'status': 'INVALID_SELECTION', 'detail': 'Use one of person, target_company, community_id.'}
    if source_person and operation not in ('distance', 'paths') or community_id and operation in ('distance', 'paths', 'catalog'):
        return {'status': 'INVALID_SELECTION'}
    by_id = {r['person_id']: r for r in people}
    if operation == 'catalog' and not person and not target_company:
        return {'status': 'OK', 'team': [by_id[s] for s in seeds], 'tier_a_decision_makers': targets}
    selected = []
    if person:
        found, error = resolve_entity(people, person)
        if error:
            return error
        selected = [found]
    elif target_company:
        found, error = resolve_entity(companies, target_company, 'target_id', 'target_name')
        if error:
            return error
        mappings = [t for t in targets if t['target_id'] == found['target_id']]
        if not mappings:
            return {'status': 'OUTSIDE_TARGET_SCOPE', 'company': found,
                    'detail': 'No DecisionMaker mapping for this company in the persisted Tier A outputs. This does not mean unreachable.'}
        selected = [dict(by_id[t['person_id']], decision_maker=t) for t in mappings]
    elif community_id:
        selected = [r for r in people if str(r['community']) == str(community_id).strip()]
        if not selected:
            return {'status': 'COMMUNITY_NOT_FOUND', 'community': community_id}
    elif operation in ('distance', 'paths'):
        selected = [dict(by_id[t['person_id']], decision_maker=t) for t in targets]
    else:
        selected = [by_id[s] for s in seeds]
    if operation == 'catalog':
        return {'status': 'OK', 'matches': selected}
    if operation in ('distance', 'paths'):
        sources = [by_id[s] for s in seeds]
        if source_person:
            source, error = resolve_entity(people, source_person)
            if error:
                return dict(error, field='source_person')
            if source['person_id'] not in seeds:
                return {'status': 'SOURCE_NOT_PRECOMPUTED', 'source': source,
                        'detail': 'No distances were precomputed FROM this person. Reachability is unknown for this query.',
                        'supported_sources': [by_id[s] for s in seeds]}
            sources = [source]
        hops = {(r['source_id'], r['target_id']): r['hops'] for r in distances}
        rows = []
        for target in selected:
            for source in sources:
                count = hops.get((source['person_id'], target['person_id']))
                rows.append({'source_id': source['person_id'], 'source_name': source['name'],
                             'target_id': target['person_id'], 'target_name': target['name'],
                             'decision_maker': target.get('decision_maker'), 'hops': count,
                             'status': 'UNREACHABLE' if count is None else 'SELF' if count == 0 else 'REACHABLE'})
        if operation == 'paths':
            if edges is None:
                return {'status': 'PATH_DATA_UNAVAILABLE'}
            try:
                for row in rows:
                    row.update(reconstruct_paths(people, distances, edges,
                               row['source_id'], row['target_id'], top_n))
            except ValueError as exc:
                return {'status': 'INCONSISTENT_PATH_DATA', 'detail': str(exc)}
            ranked = sorted((dict(source_id=r['source_id'], target_id=r['target_id'], hops=r['hops'], **route)
                             for r in rows for route in r['routes']),
                            key=lambda r: (r['target_id'], r['hops'], -r['route_strength'],
                                           tuple(p['person_id'] for p in r['people'])))
            return {'status': 'OK', 'paths': rows, 'ranked_routes': ranked,
                    'path_method': 'Routes assembled from persisted Knows edges and increasing stored seed distances. No graph refresh or distance recomputation.',
                    'path_order': 'Per target: shortest hop count first, then descending product of edge strengths, then route IDs. A heuristic model ranking, not a probability or guarantee. Per-source route limits are disclosed.',
                    'connection_meaning': 'Modeled Knows connections, not confirmed personal familiarity or guaranteed introductions.'}
        return {'status': 'OK', 'distances': rows,
                'unreachable_definition': 'Known person with no path from a covered team source in the complete persisted baseline; not a hop cutoff.'}
    groups = []
    for label in sorted({r['community'] for r in selected}):
        members = [r for r in people if r['community'] == label]
        ordered = sorted(members, key=lambda r: (-round(r['internal_betweenness'], 3), r['name'], r['person_id']))
        shown = ordered if operation == 'community' else ordered[:top_n]
        cutoff = round(shown[-1]['internal_betweenness'], 3)
        groups.append({'community': label, 'size': len(members),
                       'selected_people': [r for r in selected if r['community'] == label],
                       'members' if operation == 'community' else 'top_connectors': [
                           dict(r, displayed_betweenness=round(r['internal_betweenness'], 3),
                                rank=1 + sum(round(m['internal_betweenness'], 3) > round(r['internal_betweenness'], 3)
                                             for m in members)) for r in shown],
                       'all_scores_zero_at_display_precision': all(round(r['internal_betweenness'], 3) == 0 for r in members),
                       'same_score_members_omitted_at_cutoff': sum(round(r['internal_betweenness'], 3) == cutoff for r in ordered[len(shown):])})
    return {'status': 'OK', 'communities': groups,
            'metric': 'Exact unnormalized betweenness within each induced community, undirected and unweighted. Not global influence.',
            'ranking': 'Scores displayed/ranked to 3 decimals; alphabetical ordering breaks display ties only. Raw scores retained.'}


def read_rows(session, sql, params=None):
    return [{k.lower(): v for k, v in r.as_dict().items()} for r in session.sql(sql, params=params).collect()]


def fingerprint_sql():
    tables = [DISTANCE + '.PERSONDISTANCEPROBE', DISTANCE + '.OURSEED', DISTANCE + '.KNOWS',
              BASE + '.PERSONCOMMUNITYPROBE', BASE + '.PERSON', SOURCE + '.COMPANY',
              SOURCE + '.FUND', SOURCE + '.SPONSOR', SOURCE + '.ROLE_HISTORY', TARGET_OUTPUT + '.SCORECOMPONENT', TARGET_OUTPUT + '.DECISIONMAKER',
              TARGET_OUTPUT + '.ELIGIBLETARGET', TARGET_OUTPUT + '.COMPANY']
    return ' UNION ALL '.join(f"SELECT '{t}' AS NAME, COUNT(*) AS N, HASH_AGG(*) AS H FROM {t}" for t in tables) + ' ORDER BY NAME'


def read_target_mappings(session):
    """Read the model's persisted DecisionMaker and Act-1 Tier A outputs."""
    return read_rows(session, f"""SELECT dm.PERSON AS PERSON_ID,p.NAME,dm.KIND,
        dm.TARGET AS TARGET_ID,src.NAME AS TARGET_NAME,c.SCORE AS TARGET_SCORE,
        CASE WHEN dm.KIND='OWNER_DESIGNEE' THEN f.NAME || ' (' || sp.NAME || ')' ELSE NULL END AS VIA
        FROM {TARGET_OUTPUT}.DECISIONMAKER dm
        JOIN {TARGET_OUTPUT}.ELIGIBLETARGET e ON e.ID=dm.TARGET
        JOIN {TARGET_OUTPUT}.COMPANY c ON c.ID=e.ID
        JOIN {SOURCE}.COMPANY src ON src.COMPANY_ID=c.ID
        JOIN {BASE}.PERSON p ON p.ID=dm.PERSON
        LEFT JOIN {SOURCE}.FUND f ON f.FUND_ID=c.CURRENT_OWNER_FUND
        LEFT JOIN {SOURCE}.SPONSOR sp ON sp.SPONSOR_ID=f.SPONSOR_ID
        WHERE c.TIER='A' ORDER BY c.SCORE DESC,c.ID,dm.KIND,dm.PERSON""")


def compact_path_result(result, all_sources=False):
    """Keep every source summary; return shared people/edge context only once."""
    people, edges, summaries, routes = {}, {}, [], []
    nearest = {}
    for row in result['paths']:
        if row['hops'] is not None:
            nearest[row['target_id']] = min(nearest.get(row['target_id'], row['hops']), row['hops'])
    for row in result['paths']:
        shown = (row['routes'][:1] if row['hops']==nearest.get(row['target_id']) else []) if all_sources else row['routes']
        summaries.append({k:row[k] for k in ('source_id','source_name','target_id','target_name','hops','status','shortest_route_count')})
        summaries[-1].update(best_route_strength=row['routes'][0]['route_strength'] if row['routes'] else None,
                            routes_shown=len(shown), routes_truncated=row['shortest_route_count']>len(shown),
                            all_two_hop_intermediaries=row['all_two_hop_intermediaries'])
        for route in shown:
            ids = [p['person_id'] for p in route['people']]
            routes.append(dict(source_id=row['source_id'],target_id=row['target_id'],hops=row['hops'],
                               route_strength=route['route_strength'],person_ids=ids))
            for person in route['people']:
                people[person['person_id']] = {'name':person['name'], 'current_roles':[
                    {k:r[k] for k in ('org_id','organization_name','title','start_date')}
                    for r in person.get('current_roles',[])]}
            for edge in route['edges']:
                a,b=sorted((edge['from_id'],edge['to_id']))
                edges[(a,b)] = dict(from_id=a,to_id=b,strength=edge['strength'],evidence=edge.get('evidence'))
    routes.sort(key=lambda r:(r['target_id'],r['hops'],-r['route_strength'],tuple(r['person_ids'])))
    return {'status':'OK','source_summary':summaries, 'ranked_routes':routes,
            'people':people,'edges':list(edges.values()),
            'coverage_complete':True,'sources_returned':len({r['source_id'] for r in summaries}),
            'detail_policy':'All requested sources included. Team queries show one best route for each equally closest source. Farther sources have distances only; request source_person for route details or alternatives. Route counts and two-hop intermediary lists are complete.',
            'path_order':result['path_order']}


def lookup_handler(session, operation, person, target_company, source_person, community_id, top_n):
    """Stored procedure entry point: fixed SELECT statements, no model imports."""
    if read_rows(session, FINGERPRINT_SQL) != EXPECTED_HASHES:
        return dict(METADATA, status='BASELINE_CHANGED', detail='Persisted inputs changed since validation. Revalidation is required; no refresh was attempted.')
    people = read_rows(session, f'SELECT p.ID AS PERSON_ID,p.NAME,c.COMMUNITY,c.INTERNAL_BETWEENNESS FROM {BASE}.PERSON p JOIN {BASE}.PERSONCOMMUNITYPROBE c ON p.ID=c.ID ORDER BY p.ID')
    seeds = [r['id'] for r in read_rows(session, f'SELECT ID FROM {DISTANCE}.OURSEED ORDER BY ID')]
    companies = read_rows(session, f'SELECT COMPANY_ID AS TARGET_ID,NAME AS TARGET_NAME FROM {SOURCE}.COMPANY ORDER BY COMPANY_ID')
    distances = read_rows(session, f'SELECT SOURCE_ID,TARGET_ID,HOPS FROM {DISTANCE}.PERSONDISTANCEPROBE') if operation in ('distance', 'paths') else []
    edges = read_rows(session, f'SELECT P1,P2,STRENGTH,EVIDENCE,EVIDENCE_COUNT FROM {DISTANCE}.KNOWS WHERE STRENGTH >= 0.0') if operation == 'paths' else None
    if operation in ('paths', 'catalog'):
        roles = read_rows(session, f"""SELECT r.ROLE_ID,r.PERSON_ID,r.ORG_ID,
            COALESCE(c.NAME,sp.NAME,f.NAME,r.ORG_ID) AS ORGANIZATION_NAME,
            r.ROLE_TYPE,r.TITLE,TO_CHAR(r.START_DATE,'YYYY-MM-DD') AS START_DATE,
            TO_CHAR(r.END_DATE,'YYYY-MM-DD') AS END_DATE,
            (r.START_DATE <= DATE '2026-10-01' AND
             (r.END_DATE IS NULL OR r.END_DATE >= DATE '2026-10-01')) AS CURRENT_AS_OF_MODEL
            FROM {SOURCE}.ROLE_HISTORY r
            LEFT JOIN {SOURCE}.COMPANY c ON c.COMPANY_ID=r.ORG_ID
            LEFT JOIN {SOURCE}.SPONSOR sp ON sp.SPONSOR_ID=r.ORG_ID
            LEFT JOIN {SOURCE}.FUND f ON f.FUND_ID=r.ORG_ID ORDER BY r.PERSON_ID,r.START_DATE,r.ROLE_ID""")
        roles_by_person = {}
        for r in roles:
            roles_by_person.setdefault(r['person_id'], []).append(r)
        for p in people:
            p['role_history'] = roles_by_person.get(p['person_id'], [])
            p['current_roles'] = [r for r in p['role_history'] if r['current_as_of_model']]
    targets = read_target_mappings(session)
    result = answer_lookup(people, distances, seeds, targets, companies, operation,
                           person or '', target_company or '', source_person or '', community_id or '', top_n, edges=edges)
    if operation == 'paths' and result.get('status') == 'OK':
        company_ids = {r['decision_maker']['target_id'] for r in result['paths'] if r.get('decision_maker')}
        components = read_rows(session, f'SELECT COMPANY,CODE,POINTS,EVIDENCE FROM {TARGET_OUTPUT}.SCORECOMPONENT ORDER BY COMPANY,CODE')
        result = compact_path_result(result, all_sources=not source_person)
        result['target_score_evidence'] = [r for r in components if r['company'] in company_ids and 'CFO' in (r['evidence'] or '')]
        return dict(data_label=METADATA['data_label'],model_as_of=METADATA['model_as_of'],**result)
    return dict(METADATA, **result)


def saved_configuration():
    saved = json.loads(SAVED.read_text())
    if saved['status'] not in {'refresh and saved results validated', 'baseline refresh validated'} or not saved['preservation_passed']:
        raise RuntimeError('Successful validated saved baseline required')
    parameters, analysis = saved['parameters'], saved['analysis']
    metadata = {'data_label': 'SYNTHETIC PE DEMO DATA', 'model_as_of': '2026-10-01',
                'baseline': f"Persisted RAI Louvain max_levels={parameters['max_levels']}, seed={parameters['randomization_seed']}; exact internal betweenness ({parameters['num_pivots']} pivots).",
                'community_configuration': {'algorithm': 'Louvain', 'max_levels': parameters['max_levels'], 'randomization_seed': parameters['randomization_seed'], 'partition_source': BASE + '.PERSONCOMMUNITYPROBE', 'selection_note': 'Deployed test configuration, not an established best partition. Results refer to this saved deployed run, not earlier experimental partitions.'},
                'community_refresh_query_id': saved['refresh']['QUERY_ID'],
                'saved_evidence_sha256': hashlib.sha256(SAVED.read_bytes()).hexdigest(),
                'target_mapping_source': f'{TARGET_OUTPUT}.DECISIONMAKER joined to ELIGIBLETARGET and COMPANY.TIER=A, using the existing model rules. Target memberships and mappings are read from persisted tables, never embedded snapshot constants.',
                'community_ids': 'Raw persisted RAI labels for this partition, not the display ordinals in the analysis report.',
                'score_validation': 'All 2506 exact scores checked previously; rel_tol=2e-6, abs_tol=1e-5. Tiny signed residuals display as zero.',
                'coverage': f"{analysis['people']} people; {analysis['connections']} Knows edges; {analysis['community_count']} communities; {analysis['singletons']} singletons. Distances: five team sources, 4300 reachable ordered pairs including self; no hop cutoff.",
                'sources': [DISTANCE + '.PERSONDISTANCEPROBE', DISTANCE + '.KNOWS', SOURCE + '.ROLE_HISTORY', TARGET_OUTPUT + '.SCORECOMPONENT', BASE + '.PERSONCOMMUNITYPROBE',
                            TARGET_OUTPUT + '.DECISIONMAKER', TARGET_OUTPUT + '.ELIGIBLETARGET', TARGET_OUTPUT + '.COMPANY']}
    return saved, metadata


def procedure_sql(hashes):
    _, metadata = saved_configuration()
    constants = dict(BASE=BASE, DISTANCE=DISTANCE, SOURCE=SOURCE, TARGET_OUTPUT=TARGET_OUTPUT,
                     METADATA=metadata, FINGERPRINT_SQL=fingerprint_sql(), EXPECTED_HASHES=hashes)
    body = '\n'.join(f'{k} = {v!r}' for k, v in constants.items()) + '\n\n'
    body += '\n\n'.join(inspect.getsource(f) for f in (resolve_entity, reconstruct_paths, answer_lookup, read_rows, read_target_mappings, compact_path_result, lookup_handler))
    assert '$$' not in body
    return f"""CREATE PROCEDURE {PROCEDURE}(operation VARCHAR, person VARCHAR, target_company VARCHAR,
source_person VARCHAR, community_id VARCHAR, top_n NUMBER(38,0))
RETURNS VARIANT LANGUAGE PYTHON RUNTIME_VERSION='3.11'
PACKAGES=('snowflake-snowpark-python') HANDLER='lookup_handler'
COMMENT='Synthetic PE baseline: SELECT-only lookup of persisted distances and internal community scores.'
EXECUTE AS CALLER AS $$\n{body}\n$$"""


def agent_specification():
    fields = {
        'operation': {'type': 'string', 'enum': ['catalog', 'distance', 'paths', 'community', 'connectors'],
                      'description': 'catalog lists team and Tier A targets; distance gives hops; paths returns verified shortest routes and all two-hop intermediaries; community lists membership; connectors ranks internal betweenness.'},
        'person': {'type': 'string', 'description': 'Person name or ID. For distance or paths, this is the destination person. Empty when selecting a company, community, or default team.'},
        'target_company': {'type': 'string', 'description': 'Company name/ID to select its persisted Tier A DecisionMaker people, including CEOs and owner designees. Otherwise empty.'},
        'source_person': {'type': 'string', 'description': 'For distance or paths: source person name/ID. Empty means all five team sources. Preserve any explicitly requested non-team source.'},
        'community_id': {'type': 'string', 'description': 'Raw persisted community label; only for community/connectors. Otherwise empty.'},
        'top_n': {'type': 'integer', 'minimum': 1, 'maximum': 10, 'description': 'Maximum displayed connectors per community or routes per source/target, default 3 (up to 10). Two-hop intermediary lists are complete even when displayed routes are capped.'}}
    return {'models': {'orchestration': 'auto'}, 'orchestration': {'budget': {'seconds': 120, 'tokens': 12000}},
            'instructions': {
                'orchestration': 'Use pe_graph_lookup for every data-specific answer. For who-can-connect-us questions call paths with target_company, blank source_person and top_n=1. Read source_summary BEFORE route details; it covers all five team members. Report all equally shortest team sources, including lower-scoring alternatives, before mentioning longer routes. Never substitute a longer route for an available shorter alternative. Compact routes reference people by ID and edges by endpoint pair. If a tool response is truncated, call distance for all-source coverage and paths separately for each shortest source; do not claim a team-wide best route from incomplete coverage. Resolve names with this tool; never invent IDs. Use empty strings for unused selections. Select exactly one of person, target_company, community_id. For hop-count questions use distance; for warmer/best introductions, route comparisons, routes, introduction chains or intermediaries use paths, with target_company or person. For team-to-target questions use target_company; blank source_person means all five team seeds. Distance answers are available only FROM those five team sources; other named sources can only be checked for coverage. For multiple people/companies make separate calls. For target CEOs use target_company and filter returned DecisionMaker kind=CEO; do not redefine DecisionMaker. Preserve the requested direction and explicit source_person, even for non-team sources. Treat lookup statuses as authoritative; do not infer a distance from reversed pairs, shared community, or scores. The Knows graph is undirected: SOURCE_NOT_PRECOMPUTED describes stored source coverage, not mathematical directionality. Do not claim that reverse-distance symmetry is invalid; state that the requested source has no stored distance rows. Only persisted results are available: paths are reconstructed from stored edges and distances; no distance/community recomputation, refresh, writes, global betweenness, alternative partitions, or live-data claims. Never infer intermediaries from community membership. For two-hop questions report every all_two_hop_intermediaries entry. Use ranked_routes and route_strength to compare sources; shortest hops first and product strength second. Read current_roles for intermediaries and target_score_evidence for company context. Never redefine DecisionMaker to add a CFO. Disclose routes_truncated and shortest_route_count when routes are capped. Do not call another tool or author SQL.',
                'response': 'Identify every answer as synthetic PE demo data, model as of 2026-10-01. Be concrete and concise: default to at most 140 words unless detailed evidence is explicitly requested. For a broad who-can-connect-us question, use only: one recommendation sentence; a table of all equally shortest sources with intermediary, hops and product score; two brief evidence sentences total (not one bullet per edge); one sentence giving the other sources’ shortest distances; and one short caveat. Omit IDs, employment histories, decision-maker-definition explanations, algorithm notes, headings for caveats and follow-up offers in this default answer. Say shortest routes rather than only routes. Never imply that all alternative routes use the displayed intermediaries: when alternatives are capped, these are only the best displayed routes. Lead with one recommendation, then a small table of the equally shortest alternatives (source, intermediary, hops, product score), then one or two evidence sentences and a single short synthetic-data/model-score caveat. For farther sources state ONLY their shortest hop counts, never claim which people their routes pass through. Summarize longer routes in one sentence; do not list their chains unless asked. Do not repeat IDs, job histories, algorithm explanations or disclaimers. Interpret present/current relative to the model date, never today. Answer only what was asked, without unsolicited additional analyses, investment advice, influence claims, narratives, or guarantees of introductions. Use tool results only. Validation means agreement with the independent CSV oracle for the tested cases; never claim exact parity with the entire original demo output. Distinguish the live deployed partition from experimental partitions even when settings match. Higher modularity or team co-membership alone does not establish a better or more useful partition. For an introduction recommendation lead with the highest-ranked eligible route and label it the strongest under the model, not an objectively best real-world introduction. Route ranking is independent of Louvain and internal betweenness: rank by shortest hop count first, then product of connection strengths among equally short routes. Louvain levels and seed determine community membership and therefore within-community betweenness only; they do not determine, constrain, or rank introduction routes. Never say a route recommendation uses Louvain settings. When comparing an introduction route with centrality, explicitly distinguish target-specific route ranking from community-wide internal centrality. If mentioning Louvain settings, attach them only to the community result. Changing only the Louvain settings cannot change route rankings when the Knows graph, edge strengths and route-ranking rule stay fixed. Report the product route score and alternatives; do not present different scores as equal. A score ratio is not a probability or a claim of twice the real-world warmth. Explain each link using its persisted evidence (the strongest evidence item, not necessarily all evidence). Highlight an intermediary who currently works at the target, including title and dates from current_roles. Distinguish that useful role context from the model DecisionMaker definition. Never invent missing evidence. Say routes and product scores were calculated from stored inputs; distance/community algorithms were not rerun. Report IDs with names when useful. Distinguish UNREACHABLE (known person/no path from a covered team source) from SOURCE_NOT_PRECOMPUTED (source outside the five precomputed team sources; reachability unknown), NOT_FOUND, AMBIGUOUS, and OUTSIDE_TARGET_SCOPE. Never report missing hops as zero; SELF is zero. For EVERY community or connector answer state the deployed Louvain max_levels and seed from community_configuration. Never substitute an earlier experimental partition for this deployment or say this setting is best. Community labels are partition-specific raw IDs. When explaining internal betweenness use this definition: the unnormalized sum, over unordered pairs of OTHER community members, of the fraction of their shortest paths passing through the person; endpoints are excluded. Equal-length alternative paths reduce fractional credit, not eliminate it. Zero means no such shortest-path contribution at display precision, not isolation or any particular edge structure. Use the paths operation to identify actual modeled route edges. Never invent topology from community membership or centrality. Describe edges as modeled connections, not proven personal familiarity. A two-hop route has one intermediary. Zero internal betweenness means the metric cannot distinguish a connector in that group; do not conclude there are no useful connectors. Do not suggest automatic monitoring or imply refreshing advances the fixed model date. Use displayed_betweenness and preserve score ties. All-zero scores do not identify a unique top connector. If same_score_members_omitted_at_cutoff is positive, explicitly disclose omitted tied members. If the baseline changed or a tool fails, say so and do not give unsupported results. Target mappings come from persisted model DecisionMaker, EligibleTarget and Company outputs, filtered by Company.TIER=A. They are independently oracle-validated. A lookup reads these outputs; it does not re-evaluate eligibility or use an embedded mapping snapshot. Each lookup verifies table fingerprints; graph algorithms and independent score validation are not rerun. If describing validation, state that distinction accurately.',
                'sample_questions': [{'question': q} for q in (
                    'How many hops from each of our team members to the decision-makers of Larkspur Revenue Partners?',
                    'Which communities contain our five team members?',
                    'Who are the top three internal connectors in Dana Okafor’s community?',
                    'Can our team reach the decision-makers of Saltmarsh Home Infusion?')]},
            'tools': [{'tool_spec': {'type': 'generic', 'name': 'pe_graph_lookup',
                                    'description': 'Read-only synthetic PE baseline lookup: team-to-target hop counts, verified shortest routes, memberships and within-community betweenness. Reads persisted edges/distances; no refresh or distance recomputation.',
                                    'input_schema': {'type': 'object', 'properties': fields, 'required': list(fields)}}}],
            'tool_resources': {'pe_graph_lookup': {'type': 'procedure', 'identifier': PROCEDURE,
                                                 'execution_environment': {'type': 'warehouse', 'warehouse': f'{_cfg.WAREHOUSE}', 'query_timeout': 60}}}}


def connect():
    from relationalai.config import create_config
    connection = create_config().get_default_connection()
    connection.role = f'{_cfg.DEPLOY_ROLE}'
    connection.warehouse = f'{_cfg.WAREHOUSE}'
    return connection._create_new_session()


def preservation(session):
    import check_graphs
    result = check_graphs.community_preservation_snapshot(session)
    for table in (BASE + '.PERSONCOMMUNITYPROBE', BASE + '.PERSON', BASE + '.KNOWS',
                  BASE + '_META._INTERNAL_PLAN', BASE + '_META._INTERNAL_REFRESH_LOG'):
        result[table] = read_rows(session, f'SELECT COUNT(*) N,HASH_AGG(*) H FROM {table}')
    result['community_tasks'] = read_rows(session, f'SHOW TASKS IN SCHEMA {BASE}_META')
    result['model_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (ROOT / 'pe_deal_graph/model').glob('*.py')}
    return json.loads(json.dumps(result, default=str))


def validate_baseline(session):
    """Check saved graph identity and independently validate persisted target rules."""
    from check_rules import TARGET_EVIDENCE, read_target_outputs, validate_target_rows
    saved, _ = saved_configuration()
    current = read_rows(session, f'SELECT ID AS PERSON_ID,COMMUNITY,INTERNAL_BETWEENNESS FROM {BASE}.PERSONCOMMUNITYPROBE ORDER BY ID')
    expected = sorted([dict(person_id=r['person_id'], community=r['community'], internal_betweenness=r['betweenness']) for r in saved['rows']], key=lambda r: r['person_id'])
    if current != expected:
        raise RuntimeError('Persisted community rows differ from the validated saved run')
    seeds = read_rows(session, f'SELECT ID FROM {DISTANCE}.OURSEED ORDER BY ID')
    assert [r['id'] for r in seeds] == sorted(r['person_id'] for r in saved['analysis']['focus']['team_seeds'])
    target_evidence = json.loads(TARGET_EVIDENCE.read_text())
    if target_evidence['status'] != 'target outputs persisted and oracle validated' or not target_evidence['preservation_passed']:
        raise RuntimeError('Successful target deployment and independent validation required')
    validate_target_rows(**read_target_outputs(session))
    before = preservation(session)
    assert all(before[k] == v for k, v in saved['final_preservation_snapshot'].items())
    assert before['model_sha256'] == saved.get('current_model_sha256', target_evidence['preservation_after']['model_sha256'])
    return before


def save_report(report):
    REPORT.write_text(json.dumps(report, indent=2, default=str) + '\n')


def deploy(session):
    before = validate_baseline(session)
    agents = read_rows(session, 'SHOW AGENTS IN ACCOUNT')
    assert not any(r['name'] == AGENT.split('.')[-1] and r['database_name'] == DB and r['schema_name'] == SCHEMA for r in agents), 'Agent exists; refusing replacement'
    assert not read_rows(session, f"SHOW PROCEDURES LIKE 'PE_GRAPH_LOOKUP' IN SCHEMA {BASE}"), 'Procedure exists; refusing replacement'
    hashes = read_rows(session, fingerprint_sql())
    spec = agent_specification()
    report = {'status': 'preflight passed', 'agent': AGENT, 'procedure': PROCEDURE,
              'baseline_before': before, 'agents_before': agents, 'hashes': hashes,
              'target_mapping': read_target_mappings(session), 'specification': spec}
    save_report(report)
    session.sql(procedure_sql(hashes)).collect()
    report['procedure_created'] = True
    save_report(report)
    # The existing schema owner creates only this new agent. No broad schema grants.
    session.sql(f'USE ROLE {_cfg.ADMIN_ROLE}').collect()
    try:
        profile = json.dumps({'display_name': 'PE Graph Assistant — Synthetic Baseline'})
        session.sql(f"CREATE AGENT {AGENT} COMMENT='Synthetic PE demo: validated persisted distance and community results only.' PROFILE='{profile}' FROM SPECIFICATION $$ {json.dumps(spec)} $$").collect()
        session.sql(f'GRANT USAGE ON AGENT {AGENT} TO ROLE {_cfg.DEPLOY_ROLE}').collect()
    finally:
        session.sql(f'USE ROLE {_cfg.DEPLOY_ROLE}').collect()
    report['status'] = 'deployed; tests pending'
    save_report(report)
    verify_preservation(session, report)


def verify_preservation(session, report):
    after = preservation(session)
    agents = json.loads(json.dumps(read_rows(session, 'SHOW AGENTS IN ACCOUNT'), default=str))
    others = [r for r in agents if not (r['name'] == AGENT.split('.')[-1] and r['database_name'] == DB and r['schema_name'] == SCHEMA)]
    key = lambda r: (r['database_name'], r['schema_name'], r['name'])
    before_agents = json.loads(json.dumps(report['agents_before'], default=str))
    unchanged = sorted(others, key=key) == sorted(before_agents, key=key)
    report.update(baseline_after=after, other_agents_unchanged=unchanged,
                  preservation_passed=after == report['baseline_before'], agents_after_count=len(agents))
    save_report(report)
    assert report['preservation_passed'] and unchanged


def update_agent(session):
    """Update only this script's recorded agent specification; leave its procedure alone."""
    report = json.loads(REPORT.read_text())
    assert report['agent'] == AGENT and report['procedure'] == PROCEDURE
    verify_preservation(session, report)
    spec = agent_specification()
    session.sql(f'USE ROLE {_cfg.ADMIN_ROLE}').collect()
    try:
        session.sql(f'ALTER AGENT {AGENT} MODIFY LIVE VERSION SET SPECIFICATION = $$ {json.dumps(spec)} $$').collect()
    finally:
        session.sql(f'USE ROLE {_cfg.DEPLOY_ROLE}').collect()
    report.setdefault('previous_specifications', []).append(report['specification'])
    report['specification'] = spec
    save_report(report)


def update_lookup(session, *, communities=False):
    """Update this existing lookup and agent using validated persisted model outputs."""
    from check_rules import TARGET_EVIDENCE
    report = json.loads(REPORT.read_text())
    assert report['agent'] == AGENT and report['procedure'] == PROCEDURE
    before = validate_baseline(session)
    # This task adds a target-only profile; all protected deployed state is identical.
    permitted = {'model_sha256'}
    if communities:
        permitted.update({BASE+'.PERSONCOMMUNITYPROBE', BASE+'.PERSON', BASE+'_META._INTERNAL_PLAN',
                          BASE+'_META._INTERNAL_REFRESH_LOG', 'community_tasks'})
    assert {k:v for k,v in before.items() if k not in permitted} == {
        k:v for k,v in report['baseline_before'].items() if k not in permitted}
    target_evidence = json.loads(TARGET_EVIDENCE.read_text())
    description = {r['property']:r['value'] for r in read_rows(session,f'DESCRIBE PROCEDURE {PROCEDURE}{SIGNATURE}')}
    old_hash = hashlib.sha256(description['body'].encode()).hexdigest()
    if old_hash != report['procedure_body_sha256']:
        raise RuntimeError('Lookup procedure changed since its last recorded validation')
    grants = read_rows(session,f'SHOW GRANTS ON PROCEDURE {PROCEDURE}{SIGNATURE}')
    if any(r['privilege']!='OWNERSHIP' or r['grantee_name']!=f'{_cfg.DEPLOY_ROLE}' for r in grants):
        raise RuntimeError('Unexpected lookup grants; stop before replacement')
    report.setdefault('previous_data_sources',[]).append({k:report.get(k) for k in (
        'status','target_mapping','hashes','baseline_before','specification','procedure_tests',
        'agent_tests','validation_summary','procedure_body_sha256')})
    hashes = read_rows(session,fingerprint_sql())
    sql = procedure_sql(hashes).replace('CREATE PROCEDURE ','CREATE OR REPLACE PROCEDURE ',1)
    session.sql(sql).collect()
    report.update(status='lookup updated; live validation pending', hashes=hashes,
                  baseline_before=before, target_mapping=read_target_mappings(session),
                  target_deployment_evidence=str(TARGET_EVIDENCE.relative_to(ROOT)),
                  target_oracle_validation=target_evidence['validation'], agent_tests=[],
                  target_data_source=TARGET_OUTPUT+'.DECISIONMAKER', validation_summary={})
    current = {r['property']:r['value'] for r in read_rows(session,f'DESCRIBE PROCEDURE {PROCEDURE}{SIGNATURE}')}
    report['procedure_body_sha256']=hashlib.sha256(current['body'].encode()).hexdigest()
    assert current['body'].strip()==sql.split('AS $$\n',1)[1].rsplit('\n$$',1)[0].strip()
    save_report(report)
    update_agent(session)
    verify_preservation(session,json.loads(REPORT.read_text()))


def call_lookup(session, operation, person='', target_company='', source_person='', community_id='', top_n=3):
    value = session.sql(f'CALL {PROCEDURE}(?,?,?,?,?,?)', params=[operation, person, target_company, source_person, community_id, top_n]).collect()[0][0]
    return json.loads(value) if isinstance(value, str) else value


def chat(session, question):
    from relationalai.agent.cortex.api.client import http_client
    client = http_client(session.connection)
    response = client.post(f'/api/v2/databases/{DB}/schemas/{SCHEMA}/agents/{AGENT.split(".")[-1]}:run',
                           json={'stream': False, 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': question}]}]})
    response.raise_for_status()
    return response.json()


def live_tests(session, targets_only=False):
    """Exercise the procedure and real agent; save complete responses for factual review."""
    report = json.loads(REPORT.read_text())
    direct = {}
    direct['larkspur'] = call_lookup(session, 'distance', target_company='Larkspur Revenue Partners')
    assert {(r['source_id'], r['target_id']): r['hops'] for r in direct['larkspur']['distances']} == {
        (s, t): h for s, ceo_hops in [('P19079', 4), ('P25319', 3), ('P26028', 4), ('P26070', 4), ('P95007', 4)]
        for t, h in [('P67052', ceo_hops), ('P79001', ceo_hops + 1)]}
    direct['unreachable'] = call_lookup(session, 'distance', target_company='Saltmarsh')
    assert len(direct['unreachable']['distances']) == 10 and all(r['hops'] is None and r['status'] == 'UNREACHABLE' for r in direct['unreachable']['distances'])
    direct['unsupported_source'] = call_lookup(session, 'distance', person='Marcus Whitfield', source_person='Ruth Adeyemi')
    assert direct['unsupported_source']['status'] == 'SOURCE_NOT_PRECOMPUTED'
    direct['self'] = call_lookup(session, 'distance', person='Marcus Whitfield', source_person='Marcus Whitfield')
    assert direct['self']['distances'][0]['status'] == 'SELF' and direct['self']['distances'][0]['hops'] == 0
    direct['team_communities'] = call_lookup(session, 'community')
    assert {g['selected_people'][0]['person_id']: g['community'] for g in direct['team_communities']['communities']} == {
        'P19079': 101, 'P25319': 412, 'P26028': 179, 'P26070': 72, 'P95007': 65}
    direct['connectors'] = call_lookup(session, 'connectors', person='Dana Okafor')
    direct['unknown'] = call_lookup(session, 'distance', person='P_DOES_NOT_EXIST')
    assert direct['unknown']['status'] == 'NOT_FOUND'
    direct['ambiguous'] = call_lookup(session, 'community', person='Albrecht')
    assert direct['ambiguous']['status'] == 'AMBIGUOUS'
    if targets_only:
        direct['outside_tier_a'] = call_lookup(session, 'distance', target_company='C9820')
        assert direct['outside_tier_a']['status'] == 'OUTSIDE_TARGET_SCOPE'
    report['procedure_tests'] = direct
    report['procedure_assertions_passed'] = True
    report.setdefault('agent_tests', [])
    save_report(report)
    saved, _ = saved_configuration()
    counts = {}
    for row in saved['rows']:
        counts[row['community']] = counts.get(row['community'], 0) + 1
    singleton = next(r for r in sorted(saved['rows'], key=lambda r: r['person_id']) if counts[r['community']] == 1)
    questions = [
        ('distance', 'How many hops from each of our five team members to the decision-makers of Larkspur Revenue Partners? Include both the CEO and owner designee.'),
        ('unreachable', 'Can any of our five team members reach either decision-maker of Saltmarsh Home Infusion? Give the hop counts if available.'),
        ('unsupported_source', 'How many hops FROM Ruth Adeyemi TO Marcus Whitfield? Is he unreachable from Ruth?'),
        ('membership', 'Which persisted communities contain our five team members and the decision-makers of Larkspur Revenue Partners?'),
        ('connectors', 'Who are the top three people by internal betweenness in Dana Okafor’s community? Give their scores and explain what the scores mean.'),
        ('singleton', f'Who is the strongest connector in {singleton["name"]} ({singleton["person_id"]})’s community?'),
        ('unknown', 'How many hops from Marcus Whitfield to person P_DOES_NOT_EXIST?'),
        ('self', 'How many hops from Marcus Whitfield to himself?'),
        ('no_recompute', 'Refresh the graph and calculate global betweenness with a different Louvain seed. Then report new scores.'),
    ]
    if targets_only:
        questions = [q for q in questions if q[0] in {'distance','unreachable','membership','unsupported_source'}] + [
            ('target_catalog','List every persisted Tier A target with its score and DecisionMaker people. Where do these mappings come from?'),
            ('target_connectors','Who are the top three internal connectors in the community of Larkspur Revenue Partners’ CEO? Give scores and explain the metric.')]
    completed = {r['case'] for r in report['agent_tests']}
    for case, question in questions:
        if case in completed:
            continue
        print(f'Testing agent: {case}', flush=True)
        response = chat(session, question)
        report['agent_tests'].append({'case': case, 'question': question, 'response': response,
                                      'specification_sha256': hashlib.sha256(json.dumps(report['specification'], sort_keys=True).encode()).hexdigest(),
                                      'factual_review': 'pending'})
        save_report(report)
        print(f'Saved response: {case}', flush=True)
    verify_preservation(session, report)
    report['status'] = 'deployed; live responses saved for factual review'
    save_report(report)


def live_path_tests(session):
    """Validate compact source coverage and ranked routes against the CSV oracle."""
    import runpy
    import math
    import networkx as nx
    oracle=runpy.run_path(str(ROOT/'data/oracle.py')); data=oracle['Data']()
    pairs=oracle['build_knows'](data,set(oracle['our_seeds'](data)))
    graph=oracle['knows_graph'](data,pairs)
    result=call_lookup(session,'paths',target_company='Bayside',top_n=1)
    assert result['status']=='OK' and result['coverage_complete'] and result['sources_returned']==5
    expected_hops={'P19079':2,'P26070':2,'P25319':3,'P26028':3,'P95007':3}
    assert {r['source_id']:r['hops'] for r in result['source_summary']}==expected_hops
    assert len(json.dumps(result).encode())<10000
    for row in result['source_summary']:
        paths=list(nx.all_shortest_paths(graph,row['source_id'],row['target_id']))
        def score(path):
            return math.prod(pairs[tuple(sorted((a,b)))]['strength'] for a,b in zip(path,path[1:]))
        expected=sorted(paths,key=lambda p:(-score(p),tuple(p)))[0]
        if row['hops']==2:
            route=next(r for r in result['ranked_routes'] if r['source_id']==row['source_id'])
            assert route['person_ids']==expected
            assert math.isclose(route['route_strength'],score(expected),rel_tol=1e-9)
        else:
            assert not any(r['source_id']==row['source_id'] for r in result['ranked_routes'])
        assert math.isclose(row['best_route_strength'],score(expected),rel_tol=1e-9)
        assert row['shortest_route_count']==len(paths)
        assert row['routes_truncated']==(len(paths)>row['routes_shown'])
    assert [r['source_id'] for r in result['ranked_routes'][:2]]==['P19079','P26070']
    assert all(e['evidence'] for e in result['edges'])
    assert any(r['org_id']=='C6334' and r['start_date']=='2025-06-01' for r in result['people']['P88768']['current_roles'])
    direct={'bayside':result}
    direct['self']=call_lookup(session,'paths',person='P19079',source_person='P19079')
    assert direct['self']['source_summary'][0]['status']=='SELF'
    direct['unreachable']=call_lookup(session,'paths',person='P10001',source_person='P19079')
    assert direct['unreachable']['source_summary'][0]['status']=='UNREACHABLE'
    direct['unsupported_source']=call_lookup(session,'paths',person='P19079',source_person='P37955')
    assert direct['unsupported_source']['status']=='SOURCE_NOT_PRECOMPUTED'
    direct['cfo']=call_lookup(session,'paths',person='P88768',source_person='P19079')
    assert direct['cfo']['source_summary'][0]['hops']==1
    report=json.loads(REPORT.read_text())
    report['path_validation']={'procedure_checks':direct,'procedure_checks_passed':True,
                              'payload_bytes':len(json.dumps(result).encode()),'agent_tests':[],
                              'factual_review':'pending'}
    save_report(report)
    print('PASS: compact payload, all five sources, ranked routes and coverage cases',flush=True)
    questions=[('bayside_routes','Who can connect us to Bayside’s CEO?'),
               ('all_five','How many hops is each of our five team members from Bayside CEO Daniel Reyes?'),
               ('cfo_context','What is our strongest route to Elena Marsh, and what is her role at Bayside?')]
    for case,question in questions:
        print('Testing agent: '+case,flush=True)
        response=chat(session,question)
        report['path_validation']['agent_tests'].append(dict(case=case,question=question,response=response))
        save_report(report)
        print('Saved agent answer: '+case,flush=True)
    verify_preservation(session,report)
    report['status']='compact complete-coverage lookup deployed; answers awaiting factual review'
    save_report(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'deploy', 'update-agent', 'use-target-outputs', 'update-lookup', 'test-paths', 'test', 'test-targets', 'status', 'chat'])
    parser.add_argument('question', nargs='?')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps({'agent': AGENT, 'specification': agent_specification(), 'metadata': saved_configuration()[1]}, indent=2))
        return
    session = connect()
    try:
        if args.command == 'deploy':
            deploy(session)
            print(f'Created {AGENT}; saved {REPORT}')
        elif args.command == 'update-agent':
            update_agent(session)
            print(f'Updated specification for {AGENT}')
        elif args.command in ('use-target-outputs', 'update-lookup'):
            update_lookup(session)
            print(f'Updated lookup and instructions for {AGENT}')
        elif args.command == 'test-paths':
            live_path_tests(session)
        elif args.command == 'status':
            print(json.dumps(read_rows(session, f'DESCRIBE AGENT {AGENT}'), indent=2, default=str))
        elif args.command == 'chat':
            if not args.question:
                parser.error('chat requires a question')
            print(json.dumps(chat(session, args.question), indent=2))
        else:
            live_tests(session, targets_only=args.command=='test-targets')
    finally:
        session.close()


if __name__ == '__main__':
    main()
