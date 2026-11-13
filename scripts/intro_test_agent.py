"""Separate Cortex agent for the enriched 1M introduction experiment.

Creates one read-only lookup procedure and one agent inside the existing
CONNECTED_1M_INTRO_TEST schema. It never updates the baseline demo agent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import intro_evidence_experiment as experiment
import person_path_proc as paths

ROOT = paths.ROOT
BASE, _ = paths.schemas('connected1m')
SCHEMA = BASE + '_INTRO_TEST'
AGENT = SCHEMA + '.PE_INTRO_1M_TEST'
LOOKUP = SCHEMA + '.INTRO_LOOKUP'
DISPLAY_NAME = 'PE Introductions — Enriched 1M Test'
REPORT = ROOT / 'artifacts/intro_test_agent.json'
QUESTIONS = [
    'Who on our team can connect us to Alex Morgan, and why?',
    'How can Marcus reach Alex Morgan? Give the hops, route strength and evidence for each connection.',
    'Who on our team can connect us to Alex Morgan if every link must have strength at least 0.75?',
    'How can Dana reach Alex Morgan, and what supports those connections?',
]


# The wrapper owns no data writes. All input values use SQL bindings. The existing
# path search is called only in the isolated test schema, with its normal search cap.
LOOKUP_JS = r"""
function read(sql, binds) {
    var rs = snowflake.execute({sqlText: sql, binds: binds || []}), rows = [];
    while (rs.next()) {
        var row = [];
        for (var i = 1; i <= rs.getColumnCount(); i++) row.push(rs.getColumnValue(i));
        rows.push(row);
    }
    return rows;
}
var metadata = {
    data_label: 'Synthetic enriched 1M experiment', as_of: '2026-10-01',
    ranking: 'Fewest hops first, then highest product of link strengths; IDs break exact ties.',
    method: 'On-demand Snowflake path search on RAI-materialized base edges plus SQL-derived synthetic evidence.',
    community_status: 'Not refreshed for this enrichment; no community or centrality results are provided.'
};
function answer(value) { value.metadata = metadata; return value; }
var threshold = Number(MIN_LINK_STRENGTH);
if (MIN_LINK_STRENGTH === null || !isFinite(threshold) || threshold < 0 || threshold > 1)
    return answer({status: 'INVALID_THRESHOLD', detail: 'Minimum link strength must be a number from 0 to 1.'});
function resolve(value) {
    value = String(value || '').trim();
    if (!value || value.length > 200) return {error: {status: 'INVALID_PERSON', query: value}};
    var rows = read('SELECT ID,NAME FROM __SCHEMA__.PERSON WHERE UPPER(ID)=UPPER(?) OR LOWER(NAME)=LOWER(?) ORDER BY ID LIMIT 11', [value, value]);
    if (!rows.length)
        rows = read('SELECT ID,NAME FROM __SCHEMA__.PERSON WHERE CONTAINS(LOWER(NAME),LOWER(?)) ORDER BY ID LIMIT 11', [value]);
    if (rows.length !== 1)
        return {error: {status: rows.length ? 'AMBIGUOUS' : 'NOT_FOUND', query: value,
            matches: rows.slice(0,10).map(function(r){return {id:r[0],name:r[1]};}), more_matches: rows.length>10}};
    return {id: rows[0][0], name: rows[0][1]};
}
var target = resolve(TARGET_PERSON);
if (target.error) return answer(target.error);
var sources, sourceText = String(SOURCE_PERSON || '').trim();
if (sourceText) {
    var source = resolve(sourceText);
    if (source.error) return answer(source.error);
    sources = [[source.id,source.name]];
} else {
    sources = read('SELECT P.ID,P.NAME FROM __SCHEMA__.TEAM_SEEDS S JOIN __SCHEMA__.PERSON P ON P.ID=S.PERSON_ID ORDER BY P.ID');
}
if (!sources.length) return answer({status:'NO_TEAM_SEEDS'});

// Search once from the target. Finish the whole nearest-seed layer before ranking.
// Every eligible seed is checked for membership; farther seed distances are not computed.
function nearestTeam() {
    var members={}, nodes={}, frontier=[target.id], readCount=0, depth=0;
    sources.forEach(function(s){members[s[0]]=s[1];});
    nodes[target.id]={distance:0,score:1,count:1,next:null,link:null};
    var found=members[target.id]?[target.id]:[], status='reachable';
    while (!found.length && frontier.length && depth<12) {
        var next={};
        for (var offset=0;offset<frontier.length;offset+=500) {
            var batch=frontier.slice(offset,offset+500), marks=batch.map(function(){return '?';}).join(',');
            var edges=read('SELECT SRC,DST,STRENGTH,EVIDENCE FROM __SCHEMA__.KNOWS_EDGES WHERE SRC IN ('+marks+') AND STRENGTH>=? ORDER BY SRC,DST LIMIT 300001',batch.concat([threshold]));
            readCount+=edges.length;
            if(readCount>300000){status='search_too_large';break;}
            edges.forEach(function(e){
                var a=e[0],b=e[1];
                if(nodes[b]!==undefined)return;
                var candidate=nodes[a].score*Number(e[2]), item=next[b];
                if(!item)item=next[b]={distance:depth+1,score:-1,count:0,next:null,link:null};
                item.count+=nodes[a].count;
                if(candidate>item.score || (candidate===item.score && a<item.next)) {
                    item.score=candidate;item.next=a;
                    item.link={from:b,to:a,strength:Number(e[2]),evidence:e[3]||''};
                }
            });
        }
        if(status==='search_too_large')break;
        frontier=Object.keys(next).sort();depth++;
        frontier.forEach(function(id){nodes[id]=next[id];if(members[id])found.push(id);});
    }
    metadata.team_search={eligible_sources:sources.length,edges_read:readCount,
        algorithm:'Target-first breadth-first search; strongest shortest route within the complete nearest-team layer.',
        farther_sources:'Not ranked: strictly farther than the nearest layer. Individual distances require a named-source query.'};
    if(!found.length) {
        if(status!=='search_too_large')status=frontier.length?'beyond_max_hops':'unreachable';
        return sources.map(function(s){return {source_id:s[0],source_name:s[1],status:status,hops:null,
            route:[],route_names:[],links:[],route_strength:null,shortest_route_count:null};});
    }
    var results=found.map(function(id){
        var route=[id],links=[],at=id;
        while(nodes[at].next!==null){links.push(nodes[at].link);at=nodes[at].next;route.push(at);}
        return {source_id:id,source_name:members[id],status:id===target.id?'self':'reachable',hops:nodes[id].distance,
            route:route,links:links,route_strength:nodes[id].score,shortest_route_count:nodes[id].count};
    });
    var routeIds={};results.forEach(function(r){r.route.forEach(function(id){routeIds[id]=true;});});
    var keys=Object.keys(routeIds), names={};
    read('SELECT ID,NAME FROM __SCHEMA__.PERSON WHERE ID IN ('+keys.map(function(){return '?';}).join(',')+')',keys)
        .forEach(function(r){names[r[0]]=r[1];});
    results.forEach(function(r){r.route_names=r.route.map(function(id){return names[id]||id;});
        r.links.forEach(function(l,i){l.from_name=r.route_names[i];l.to_name=r.route_names[i+1];});});
    return results;
}

var rows = [], personIds = {};
if (!sourceText) rows=nearestTeam();
else sources.forEach(function(source) {
    var result = read('CALL __SCHEMA__.PERSON_PATH(?,?,?,?)', [source[0],target.id,12,threshold])[0][0];
    if (typeof result === 'string') result = JSON.parse(result);
    var item = {
        source_id: source[0], source_name: source[1], status: result.status,
        hops: result.distance === undefined ? null : result.distance,
        route: result.route || [], route_names: result.route_names || [],
        route_strength: result.status === 'self' ? 1 : (result.route_strength === undefined ? null : result.route_strength),
        shortest_route_count: result.status === 'self' ? 1 : (result.shortest_route_count === undefined ? null : result.shortest_route_count),
        links: result.hops || []
    };
    item.route.forEach(function(id){personIds[id]=true;});
    item.links.forEach(function(link,i) {
        link.from_name = item.route_names[i]; link.to_name = item.route_names[i+1];
    });
    rows.push(item);
});
function reachable(row){return row.status === 'reachable' || row.status === 'self';}
rows.sort(function(a,b) {
    var da=reachable(a)?a.hops:Infinity, db=reachable(b)?b.hops:Infinity;
    if (da!==db) return da-db;
    if (a.route_strength!==b.route_strength) return (b.route_strength||0)-(a.route_strength||0);
    return a.source_id < b.source_id ? -1 : a.source_id > b.source_id ? 1 : 0;
});
var complete = rows.every(function(r){return reachable(r) || r.status==='unreachable';});
var best = complete && rows.length && reachable(rows[0]) ? rows[0] : null;
var ties = best ? rows.filter(function(r){return reachable(r) && r.hops===best.hops && r.route_strength===best.route_strength;}) : [];
var summaries = rows.map(function(r){return {source_id:r.source_id,source_name:r.source_name,status:r.status,
    hops:r.hops,route_strength:r.route_strength};});
var shown = sourceText ? rows : rows.filter(function(r){return best && reachable(r) && r.hops===best.hops;});
personIds = {};
shown.forEach(function(r){r.route.forEach(function(id){personIds[id]=true;});});
var ids = Object.keys(personIds), roles = [];
if (ids.length) {
    var marks = ids.map(function(){return '?';}).join(',');
    roles = read('SELECT PERSON_ID,TITLE,ORG_NAME,TO_VARCHAR(START_DATE),TO_VARCHAR(END_DATE) FROM __SCHEMA__.ROLE_HISTORY WHERE PERSON_ID IN ('+marks+") AND START_DATE<='2026-10-01'::DATE AND (END_DATE IS NULL OR END_DATE>'2026-10-01'::DATE) ORDER BY PERSON_ID,ROLE_ID",ids)
        .map(function(r){return {person_id:r[0],title:r[1],organization:r[2],start_date:r[3],end_date:r[4]};});
}
var dealLinks = [];
shown.forEach(function(r){r.links.forEach(function(link){if (link.evidence.indexOf('K2')===0) dealLinks.push(link);});});
if (dealLinks.length) {
    var parties = read('SELECT D.TRANSACTION_ID,D.LEAD_PERSON_ID,P.NAME,D.PARTY_ROLE FROM __SCHEMA__.DEAL_PARTY D JOIN __SCHEMA__.PERSON P ON P.ID=D.LEAD_PERSON_ID WHERE D.LEAD_PERSON_ID IN ('+marks+') ORDER BY D.TRANSACTION_ID,D.LEAD_PERSON_ID',ids);
    dealLinks.forEach(function(link){
        var groups = {};
        parties.forEach(function(p){
            if (p[1]===link.from || p[1]===link.to) {
                if (!groups[p[0]]) groups[p[0]]=[];
                groups[p[0]].push({person_id:p[1],name:p[2],party_role:p[3]});
            }
        });
        var paired = Object.keys(groups).filter(function(tid){
            return groups[tid].some(function(p){return p.person_id===link.from;}) && groups[tid].some(function(p){return p.person_id===link.to;});
        });
        link.deal_participants = paired.map(function(tid){return {transaction_id:tid,participants:groups[tid]};});
        if (paired.length===1)
            link.evidence=link.evidence.split(';')[0]+'; '+groups[paired[0]].map(function(p){return p.name+': '+p.party_role;}).join('; ');
    });
}
return answer({status: complete ? 'OK' : 'INCOMPLETE_SEARCH', target:{id:target.id,name:target.name},
    scope: sourceText ? 'requested person' : 'nearest sources among all current team seeds', source_count:sources.length,
    min_link_strength:threshold, max_hops:12, team_comparison_complete:complete,
    best_source_id:best?best.source_id:null, tied_best_source_ids:ties.map(function(r){return r.source_id;}),
    source_summary:summaries, source_summary_scope:sourceText?'requested source':'nearest team layer only', farther_source_count:complete&&best&&!sourceText?sources.length-rows.length:null, routes:shown, added_role_context:roles,
    route_display:'One strongest shortest route for each nearest team source, or the requested source. source_summary covers the nearest layer only for team searches; all eligible seeds were considered. Longer sources have no route details here. Never generalize to undisplayed routes.',
    strength_note:'Product of modeled link strengths, not a probability. The threshold applies to each link, not to the product.'});
"""


def lookup_sql():
    body = LOOKUP_JS.replace('__SCHEMA__', SCHEMA)
    return f"""CREATE PROCEDURE {LOOKUP}(TARGET_PERSON VARCHAR, SOURCE_PERSON VARCHAR, MIN_LINK_STRENGTH FLOAT)
RETURNS VARIANT LANGUAGE JAVASCRIPT
COMMENT='Read-only introduction search for isolated synthetic enriched 1M experiment.'
EXECUTE AS CALLER
AS $$\n{body}\n$$"""


def route_specification():
    fields = {
        'target_person': {'type':'string', 'description':'Destination person name or ID, as supplied by the user. Names are resolved by the tool. Do not guess IDs.'},
        'source_person': {'type':'string', 'description':'Named source person, or empty string for all current team members (100 in this experiment). Who can connect us means empty string.'},
        'min_link_strength': {'type':'number', 'minimum':0, 'maximum':1, 'description':'Minimum strength of EVERY individual link. Default 0.0; use 0.75 only when requested. This is not a minimum product score.'},
    }
    return {
        'models': {'orchestration':'auto'},
        'orchestration': {'budget':{'seconds':120,'tokens':8000}},
        'instructions': {
            'orchestration': (
                'This is the isolated enriched million-person synthetic experiment, not the original baseline PE demo. '
                'For every data-specific route, hop, strength, connection or evidence answer call intro_lookup. '
                'Pass person names from the question; never invent IDs. For who can connect us/team questions '
                'source_person MUST be empty so the tool checks the whole team. For a named source preserve it. '
                'Set min_link_strength=0 unless a numeric per-link threshold is explicitly requested. '
                'Use conversation context for follow-up references, but call the tool again if the target, source or threshold changes. '
                'The tool searches routes on demand; do not claim it merely reads precomputed distances. '
                'Only this tool is available: no SQL authoring, refresh, writes, or engine changes. '
                'Company-to-person resolution, communities and betweenness are outside this test agent; do not reuse old partitions. '
                'Ask for a person when only a company or unspecified executive is given. Ask a short clarification '
                'if a requested strength could mean a minimum route product rather than a per-link threshold. '
                'For AMBIGUOUS show the returned candidate names; for NOT_FOUND state not found, not unreachable. '
                'For INCOMPLETE_SEARCH report the limitation and do not claim a team-wide best source. '
                'beyond_max_hops means not found within 12 hops; search_too_large means the search limit was reached, '
                'neither establishes disconnection. Distinguish zero-hop self from missing distance. '
                'source_count reports the eligible team size. For team searches source_summary covers only the nearest layer; farther source distances are deliberately not calculated. routes contains details only for the nearest sources or the requested person. '
                'Never infer which intermediaries longer sources use, or claim that all shortest routes pass through a person. '
                'Only one route per displayed source is supplied; shortest_route_count may be greater than one. '
                'Use returned routes, evidence, roles and source coverage only. Never infer personal familiarity or future success.'
            ),
            'response': (
                'Be concrete and concise. For a team question use ONLY: one recommendation sentence with the named route, '
                'a table of up to five nearest sources with hops and product strength, and the total eligible team size, one evidence sentence, and the short synthetic-data line. '
                'Keep this default answer under 150 words. Do not add sections or describe the routes of farther sources. '
                'For an individual route question give the route, hops, product and a small link-evidence table. '
                'State the recommended person first, '
                'the named route, hop count and product strength (3 decimals), followed by one or two sentences '
                'of actual CRM, employment-overlap or deal evidence. For team questions include a compact '
                'table of the nearest sources with hops and product scores. Say the comparison considered 100 employees; do not invent distances for farther sources. Disclose any omitted tied candidates. '
                'Call it best under the model, not objectively best in real life. Ranking is fewest hops first, '
                'then highest product among equal-hop routes; a shorter weaker route can outrank a longer stronger route. '
                'If relevant state that distinction explicitly. Never say every route goes through someone: only the displayed routes are known. '
                'Preserve ties, and say one displayed shortest route '
                'if shortest_route_count exceeds one. Report thresholds as per-link thresholds. Do not convert '
                'scores to success percentages or claim that twice the score means twice as warm. '
                'Dates/current roles are relative to 2026-10-01. Added role context does not establish a CEO role. '
                'End with one short line: Synthetic data; as of 2026-10-01; scores are not probabilities. '
                'Person-level CRM identifies a counterparty; it does NOT establish a one-on-one meeting. Never describe it as one-on-one. '
                'Use the named deal_participants to associate each person with seller or advisor roles; never guess the association. '
                'Only say a route is shown if you actually display its named chain. Team summary rows are not displayed routes. '
                'Do not invent evidence, expand the test into the original demo, mention internal schema names, '
                'offer automated monitoring, or repeat caveats. Explain execution details only if asked: '
                'RAI produced the base connections; SQL derives added evidence; Snowflake searches routes at question time.'
            ),
            'sample_questions':[{'question':q} for q in QUESTIONS],
        },
        'tools':[{'tool_spec':{'type':'generic','name':'intro_lookup',
            'description':'Find the strongest shortest route from a named person or the whole team to a person in the enriched 1M synthetic graph. Returns all source hop counts, product strengths, named paths and CRM/employment/deal evidence. Optional minimum individual-link strength.',
            'input_schema':{'type':'object','properties':fields,'required':list(fields)}}}],
        'tool_resources':{'intro_lookup':{'type':'procedure','identifier':LOOKUP,
            'execution_environment':{'type':'warehouse','warehouse':paths._cfg.WAREHOUSE,'query_timeout':90}}},
    }


def rows(cur, sql):
    cur.execute(sql)
    names=[c[0] for c in cur.description]
    return [dict(zip(names,row)) for row in cur.fetchall()]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def demo_snapshot(con):
    """Small baseline-only checks; no graph scans at million-person scale."""
    cur=con.cursor()
    demo=paths._cfg.schema('COMMUNITY')
    result={'agent_sha256':digest(rows(cur,f'DESCRIBE AGENT {demo}.PE_GRAPH_ASSISTANT'))}
    signature=demo+'.PE_GRAPH_LOOKUP(VARCHAR,VARCHAR,VARCHAR,VARCHAR,VARCHAR,NUMBER)'
    result['lookup_sha256']=digest(cur.execute('SELECT GET_DDL(%s,%s)',('PROCEDURE',signature)).fetchone()[0])
    for table in (paths._cfg.schema('DEPLOY')+'.PERSONDISTANCEPROBE',demo+'.PERSONCOMMUNITYPROBE'):
        result[table]=cur.execute(f'SELECT COUNT(*), HASH_AGG(*) FROM {table}').fetchone()
    result['local_demo_code_sha256']=hashlib.sha256((ROOT/'scripts/pe_cortex_agent.py').read_bytes()).hexdigest()
    return json.loads(json.dumps(result))


def save(report):
    REPORT.write_text(json.dumps(report,indent=2,default=str)+'\n')


def deploy(con):
    cur=con.cursor()
    # These names belong only to the new agent. CREATE refuses to replace them.
    assert not rows(cur,f'SHOW AGENTS IN SCHEMA {SCHEMA}'), 'Test schema already has an agent; inspect it before deployment'
    existing=rows(cur,f"SHOW PROCEDURES LIKE 'INTRO_LOOKUP' IN SCHEMA {SCHEMA}")
    assert not [r for r in existing if r.get('is_builtin')=='N'], 'Lookup already exists'
    experiment.validate_added(con,SCHEMA)
    report={'status':'prepared','agent':AGENT,'display_name':DISPLAY_NAME,'lookup':LOOKUP,
            'before':demo_snapshot(con),'specification':specification(),'created':[]}
    save(report)
    cur.execute(lookup_sql()); report['created'].append(LOOKUP);save(report)
    profile=json.dumps({'display_name':DISPLAY_NAME}).replace("'","''")
    cur.execute(f"CREATE AGENT {AGENT} COMMENT='Isolated enriched 1M synthetic introduction test; on-demand routes and evidence.' PROFILE='{profile}' FROM SPECIFICATION $$ {json.dumps(specification())} $$")
    report['created'].append(AGENT);save(report)
    # Existing database/warehouse access is reused. New grants concern only this test schema/tool/agent.
    for sql in (f'GRANT USAGE ON SCHEMA {SCHEMA} TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT USAGE ON PROCEDURE {LOOKUP}(VARCHAR,VARCHAR,FLOAT) TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT USAGE ON AGENT {AGENT} TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT SELECT ON VIEW {SCHEMA}.PERSON TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT SELECT ON VIEW {SCHEMA}.TEAM_SEEDS TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT SELECT ON VIEW {SCHEMA}.KNOWS_EDGES TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT SELECT ON TABLE {SCHEMA}.ROLE_HISTORY TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT SELECT ON TABLE {SCHEMA}.DEAL_PARTY TO ROLE {paths._cfg.DEPLOY_ROLE}',
                f'GRANT USAGE ON PROCEDURE {SCHEMA}.PERSON_PATH(VARCHAR,VARCHAR,FLOAT,FLOAT) TO ROLE {paths._cfg.DEPLOY_ROLE}'):
        cur.execute(sql)
    report['after']=demo_snapshot(con)
    assert report['before']==report['after'], 'Existing demo changed during deployment'
    report['demo_unchanged']=True;report['status']='created; live tests pending';save(report)
    print(f'Created {AGENT}',flush=True)


def lookup(con,target,source='',threshold=0):
    cur=con.cursor();start=time.perf_counter()
    value=cur.execute(f'CALL {LOOKUP}(%s,%s,%s)',(target,source,threshold)).fetchone()[0]
    return (json.loads(value) if isinstance(value,str) else value),time.perf_counter()-start,cur.sfqid


def chat(con,question):
    from relationalai.agent.cortex.api.client import http_client
    db,schema,name=AGENT.split('.')
    client=http_client(con,timeout=180)
    started=time.perf_counter()
    response=client.post(f'/api/v2/databases/{db}/schemas/{schema}/agents/{name}:run',
        json={'stream':False,'messages':[{'role':'user','content':[{'type':'text','text':question}]}]})
    response.raise_for_status()
    return response.json(),time.perf_counter()-started


def test(con):
    report=json.loads(REPORT.read_text())
    assert report['agent']==AGENT and report['lookup']==LOOKUP
    con.cursor().execute(f'USE ROLE {paths._cfg.DEPLOY_ROLE}')
    con.cursor().execute('USE SECONDARY ROLES NONE')
    report['tested_role']=paths._cfg.DEPLOY_ROLE
    reference=json.loads((ROOT/'artifacts/intro_evidence_1m.json').read_text())
    inputs=[('',0),('Marcus',0),('',0.75),('Dana',0)]
    report['direct_tests']=[]
    for (source,threshold),expected in zip(inputs,reference['questions']):
        result,elapsed,query_id=lookup(con,'Alex Morgan',source,threshold)
        assert result['status']=='OK' and result['team_comparison_complete']
        assert result['best_source_id']==expected['winner']['source_id']
        actual={r['source_id']:r for r in result['source_summary']}
        wanted={r['source_id']:r for r in expected['attempts'][-1]['results']}
        assert set(actual)==set(wanted)
        for source_id,row in actual.items():
            exp=wanted[source_id]
            assert row['hops']==exp['distance']
            assert math.isclose(row['route_strength'],exp['route_strength'],abs_tol=1e-6)
        expected_details={sid for sid,r in wanted.items() if source or r['distance']==expected['winner']['distance']}
        assert {r['source_id'] for r in result['routes']}==expected_details
        for row in result['routes']:
            assert row['route']==wanted[row['source_id']]['route']
            assert row['shortest_route_count']==wanted[row['source_id']]['shortest_route_count']
            assert all(link['evidence'] and link['strength']>=threshold-1e-6 for link in row['links'])
            for link in row['links']:
                if link['evidence'].startswith('K2'):
                    participants=link['deal_participants'][0]['participants']
                    assert {p['person_id']:p['party_role'] for p in participants}=={experiment.TARGET:'seller',experiment.JORDAN:'sell_side_advisor'}
        report['direct_tests'].append(dict(source=source,threshold=threshold,result=result,seconds=elapsed,query_id=query_id))
        save(report);print(f'PASS tool source={source or "team"} threshold={threshold}: {elapsed:.3f}s',flush=True)
    report['edge_cases']=[]
    for target,source,threshold,status in [('Unknown Person XYZ','',0,'NOT_FOUND'),('Alex Morgan','',1.1,'INVALID_THRESHOLD'),('Alex Morgan','Alex Morgan',0,'OK')]:
        result,elapsed,qid=lookup(con,target,source,threshold)
        assert result['status']==status
        if target==source:
            assert result['routes'][0]['status']=='self' and result['routes'][0]['hops']==0
        report.setdefault('edge_cases',[]).append(dict(target=target,source=source,threshold=threshold,result=result,seconds=elapsed,query_id=qid))
        save(report)
    report['agent_tests']=[]
    for question in QUESTIONS:
        print('Asking Cortex: '+question,flush=True)
        response,elapsed=chat(con,question)
        report['agent_tests'].append(dict(question=question,response=response,seconds=elapsed,factual_review='pending'))
        save(report);print(f'Saved Cortex response in {elapsed:.3f}s',flush=True)
    con.cursor().execute(f'USE ROLE {paths._cfg.ADMIN_ROLE}')
    con.cursor().execute('USE SECONDARY ROLES ALL')
    report['after']=demo_snapshot(con)
    assert report['before']==report['after']
    report['demo_unchanged']=True;report['status']='live responses saved; factual review pending';save(report)



def update(con):
    """Refine only this recorded test agent and lookup."""
    report=json.loads(REPORT.read_text())
    assert report['agent']==AGENT and report['lookup']==LOOKUP
    cur=con.cursor()
    cur.execute(lookup_sql().replace('CREATE PROCEDURE','CREATE OR REPLACE PROCEDURE',1))
    cur.execute(f'GRANT USAGE ON PROCEDURE {LOOKUP}(VARCHAR,VARCHAR,FLOAT) TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'GRANT SELECT ON TABLE {SCHEMA}.DEAL_PARTY TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'ALTER AGENT {AGENT} MODIFY LIVE VERSION SET SPECIFICATION = $$ {json.dumps(specification())} $$')
    report.setdefault('previous_test_rounds',[]).append({'agent_tests':report.get('agent_tests',[]),
        'finding':'Refined route scope and named deal evidence; prior responses retained for audit.'})
    report['agent_tests']=[];report['specification']=specification()
    report['status']='test-only tool and instructions updated; retest pending';save(report)
    print('Updated only '+AGENT,flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['prepare','deploy','test','update','attributes','expand','test-expanded','revise','test-revised'])
    args=ap.parse_args()
    if args.command=='prepare':
        print(json.dumps({'agent':AGENT,'specification':specification()},indent=2));return
    con=paths.connect()
    try:
        if args.command=='deploy':deploy(con)
        elif args.command=='update':update(con)
        elif args.command=='attributes':install_attributes(con)
        elif args.command=='expand':expand(con)
        elif args.command=='revise':revise(con)
        elif args.command=='test-revised':test_revised(con)
        elif args.command=='test-expanded':test_expanded(con)
        else:
            count=con.cursor().execute(f'SELECT COUNT(*) FROM {SCHEMA}.TEAM_SEEDS').fetchone()[0]
            definition=con.cursor().execute('SELECT GET_DDL(%s,%s)',('VIEW',SCHEMA+'.TEAM_SEEDS')).fetchone()[0]
            if 'TEAM_MEMBERS' in definition.upper():test_revised(con)
            elif count==100:test_expanded(con)
            else:test(con)
    finally:con.close()



# Attribute discovery is separate from route search: resolve actual records first.
def attribute_view_sql():
    return f'''CREATE OR REPLACE VIEW {SCHEMA}.PERSON_ATTRIBUTES AS
    SELECT R.PERSON_ID,P.NAME,R.ORG_ID,COALESCE(C.NAME,S.NAME,I.NAME,R.ORG_ID) ORGANIZATION,
           R.ROLE_TYPE,R.TITLE,R.START_DATE,R.END_DATE
    FROM {BASE}_SRC.ROLE_HISTORY R JOIN {SCHEMA}.PERSON P ON P.ID=R.PERSON_ID
    LEFT JOIN {BASE}_SRC.COMPANY C ON C.COMPANY_ID=R.ORG_ID
    LEFT JOIN {BASE}_SRC.SPONSOR S ON S.SPONSOR_ID=R.ORG_ID
    LEFT JOIN {BASE}_SRC.INTERMEDIARY I ON I.INTERMEDIARY_ID=R.ORG_ID
    UNION ALL
    SELECT R.PERSON_ID,P.NAME,R.ORG_ID,R.ORG_NAME,R.ROLE_TYPE,R.TITLE,R.START_DATE,R.END_DATE
    FROM {SCHEMA}.ROLE_HISTORY R JOIN {SCHEMA}.PERSON P ON P.ID=R.PERSON_ID'''


def attribute_procedure_sql():
    return fr'''CREATE OR REPLACE PROCEDURE {SCHEMA}.FIND_PEOPLE(COMPANY VARCHAR,TITLE VARCHAR,CURRENT_ONLY BOOLEAN)
    RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS CALLER AS $$
    function read(sql,binds){{var rs=snowflake.execute({{sqlText:sql,binds:binds}}),out=[];
      while(rs.next()){{var row={{}};for(var i=1;i<=rs.getColumnCount();i++)row[rs.getColumnName(i).toLowerCase()]=rs.getColumnValue(i);out.push(row);}}return out;}}
    var company=String(COMPANY||'').trim(), title=String(TITLE||'').trim();
    if(!company && !title)return {{status:'FILTER_REQUIRED',detail:'Supply a company or job title.'}};
    if(company.length>200||title.length>200)return {{status:'INVALID_FILTER'}};
    var aliases={{ceo:'Chief Executive Officer',cfo:'Chief Financial Officer',coo:'Chief Operating Officer',cto:'Chief Technology Officer'}};
    var expanded=aliases[title.toLowerCase()]||title;
    var companyFilter='(?=\'\' OR CONTAINS(LOWER(ORGANIZATION),LOWER(?)) OR UPPER(ORG_ID)=UPPER(?))';
    var companyExists=read('SELECT DISTINCT ORG_ID,ORGANIZATION FROM {SCHEMA}.PERSON_ATTRIBUTES WHERE '+companyFilter+' LIMIT 11',[company,company,company]);
    if(company && !companyExists.length)return {{status:'COMPANY_NOT_IN_DATA',company:company,detail:'No matching company in this 1M fixture. This is not an unreachable-person result.'}};
    var sql='SELECT DISTINCT PERSON_ID,NAME,ORG_ID,ORGANIZATION,ROLE_TYPE,TITLE,TO_VARCHAR(START_DATE) START_DATE,TO_VARCHAR(END_DATE) END_DATE FROM {SCHEMA}.PERSON_ATTRIBUTES WHERE '+companyFilter+
      " AND (?='' OR CONTAINS(LOWER(TITLE),LOWER(?)) OR LOWER(ROLE_TYPE)=LOWER(?) OR CONTAINS(LOWER(TITLE),LOWER(?)))"+
      (CURRENT_ONLY?" AND START_DATE<='2026-10-01'::DATE AND (END_DATE IS NULL OR END_DATE>'2026-10-01'::DATE)":"")+
      ' ORDER BY PERSON_ID,ORG_ID,START_DATE LIMIT 11';
    var matches=read(sql,[company,company,company,title,title,title,expanded]);
    return {{status:matches.length?'MATCHES':'NO_MATCHING_ROLE',as_of:'2026-10-01',company:company,title:title,
      current_only:CURRENT_ONLY,matches:matches.slice(0,10),more_matches:matches.length>10,
      detail:'Use matched person IDs with intro_lookup. Multiple roles can belong to the same person; do not silently choose among different people.'}};
    $$'''



def specification():
    spec=route_specification()
    instruction=spec['instructions']['orchestration']
    instruction=instruction.replace('Only this tool is available:', 'Use only the configured tools:')
    instruction=instruction.replace('Company-to-person resolution, communities and betweenness are outside this test agent; do not reuse old partitions. Ask for a person when only a company or unspecified executive is given. ',
      'Use find_people when the target is described by company, title or current/former employment. Pass company and title separately; current_only=true unless former/historical employment is requested. Resolve the records yourself before asking the user for a name. For one matched person call intro_lookup using that returned person_id. For multiple distinct matches show names and roles and ask which person, unless the user explicitly requests comparing them; then evaluate every match or disclose a truncated search. COMPANY_NOT_IN_DATA means this fixture lacks the company; NO_MATCHING_ROLE means the company exists but the role is absent. Neither means unreachable. Never invent a CEO or borrow a person from another dataset. Communities and betweenness are outside this enriched test. ')
    spec['instructions']['orchestration']=instruction
    spec['tools'].append({'tool_spec':{'type':'generic','name':'find_people','description':'Resolve people by company name or ID, job title/role (including CEO/CFO aliases), and current versus historical employment. Returns actual matched IDs and role records before introduction search.',
      'input_schema':{'type':'object','properties':{'company':{'type':'string','description':'Company name or ID, or empty string.'},'title':{'type':'string','description':'Role or job-title phrase, or empty string for anyone at the company.'},'current_only':{'type':'boolean','description':'True for current employment as of 2026-10-01; false to include historical roles.'}},'required':['company','title','current_only']}}})
    spec['tool_resources']['find_people']={'type':'procedure','identifier':SCHEMA+'.FIND_PEOPLE','execution_environment':{'type':'warehouse','warehouse':paths._cfg.WAREHOUSE,'query_timeout':60}}
    spec['instructions']['sample_questions']=[{'question':q} for q in ['Who can connect us to the Director of Partnerships at Harbor Analytics?', 'Who can introduce us to the Head of Customer Operations at Harbor Analytics?', 'Who works at Harbor Analytics?',QUESTIONS[2]]]
    import intro_contacts
    return intro_contacts.configure(spec,SCHEMA,paths._cfg.WAREHOUSE)


def install_attributes(con):
    import intro_contacts
    cur=con.cursor();cur.execute(attribute_view_sql());cur.execute(attribute_procedure_sql())
    cur.execute(intro_contacts.attribute_sql(SCHEMA));cur.execute(intro_contacts.contacts_sql(SCHEMA))
    for signature in ('SEARCH_PEOPLE(VARCHAR,VARCHAR,VARCHAR,VARCHAR,BOOLEAN,FLOAT,FLOAT)','PERSON_CONTACTS(VARCHAR,FLOAT,BOOLEAN,FLOAT,FLOAT)'):
        cur.execute(f'GRANT USAGE ON PROCEDURE {SCHEMA}.{signature} TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'GRANT SELECT ON VIEW {SCHEMA}.PERSON_ATTRIBUTES TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'GRANT SELECT ON VIEW {SCHEMA}.ADDED_EVIDENCE TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'GRANT USAGE ON PROCEDURE {SCHEMA}.FIND_PEOPLE(VARCHAR,VARCHAR,BOOLEAN) TO ROLE {paths._cfg.DEPLOY_ROLE}')
    cur.execute(f'ALTER AGENT {AGENT} MODIFY LIVE VERSION SET SPECIFICATION = $$ {json.dumps(specification())} $$')



def expand(con):
    """Extend only the separate test data, tool and agent; record baseline preservation."""
    before=demo_snapshot(con)
    fixture=experiment.expand_team(con)
    cur=con.cursor()
    cur.execute(lookup_sql().replace('CREATE PROCEDURE','CREATE OR REPLACE PROCEDURE',1))
    cur.execute(f'GRANT USAGE ON PROCEDURE {LOOKUP}(VARCHAR,VARCHAR,FLOAT) TO ROLE {paths._cfg.DEPLOY_ROLE}')
    install_attributes(con)
    after=demo_snapshot(con)
    if before!=after:raise RuntimeError('Original demo snapshot changed')
    report={'status':'expanded; live route validation pending','seeds':len(fixture['seeds']),
            'raw_rows':{k:len(fixture[k]) for k in ('labels','roles','parties','crm')},
            'added_companies':fixture['companies'],'original_demo_unchanged':True,
            'original_demo_snapshot':before,'schema':SCHEMA}
    (ROOT/'artifacts/intro_expanded_1m.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def test_expanded(con):
    """Check raw evidence independently, then routes and actual attribute-agent calls."""
    import networkx as nx
    fixture=experiment.expanded_fixture(); cur=con.cursor()
    report_path=ROOT/'artifacts/intro_expanded_1m.json'
    report=json.loads(report_path.read_text())
    expected=experiment.original_oracle(fixture)
    actual=cur.execute(f'SELECT P1,P2,MAX(STRENGTH) FROM {SCHEMA}.ADDED_EVIDENCE GROUP BY P1,P2').fetchall()
    assert {(a,b) for a,b,_ in actual}==set(expected)
    for a,b,w in actual:assert math.isclose(float(w),expected[a,b]['strength'],abs_tol=1e-8),(a,b,w)
    report['evidence_pairs_validated']=len(actual)
    assert cur.execute(f'SELECT COUNT(*),COUNT(DISTINCT ID) FROM {SCHEMA}.PERSON').fetchone()==(1000000,1000000)
    assert {r[0] for r in cur.execute(f'SELECT PERSON_ID FROM {SCHEMA}.TEAM_SEEDS')}==set(fixture['seeds'])
    report['people']=1000000
    con.cursor().execute(f'USE ROLE {paths._cfg.DEPLOY_ROLE}');con.cursor().execute('USE SECONDARY ROLES NONE')
    cases=[('Harbor Analytics','Director of Partnerships',experiment.TARGET,0),
           ('Cedarbridge Health','CEO','SCALE_P000700000',0),
           ('Willow Diagnostics','CFO','SCALE_P000700006',0),
           ('Cedarbridge Health','CEO','SCALE_P000700000',0.75)]
    report['direct_tests']=[]; report['agent_tests']=[]
    for company,title,target,threshold in cases:
        raw=cur.execute(f'CALL {SCHEMA}.FIND_PEOPLE(%s,%s,TRUE)',(company,title)).fetchone()[0]
        attr=json.loads(raw) if isinstance(raw,str) else raw
        assert {r['person_id'] for r in attr['matches']}=={target},attr
        near=[r[0] for r in cur.execute(f'SELECT DST FROM {SCHEMA}.KNOWS_EDGES WHERE SRC=%s AND STRENGTH >= %s',(target,threshold))]
        ids=sorted(set(fixture['seeds']+[target]+near))
        edge_rows=cur.execute(f"SELECT SRC,DST,STRENGTH FROM {SCHEMA}.KNOWS_EDGES WHERE SRC IN ({','.join(['%s']*len(ids))}) AND STRENGTH >= %s",(*ids,threshold)).fetchall()
        g=nx.Graph();g.add_nodes_from(ids);g.add_weighted_edges_from((a,b,float(w)) for a,b,w in edge_rows)
        reference=[]
        for source in fixture['seeds']:
            try:distance=nx.shortest_path_length(g,source,target)
            except nx.NetworkXNoPath:continue
            if distance>3:continue
            routes=list(nx.all_shortest_paths(g,source,target))
            products=[math.prod(g[a][b]['weight'] for a,b in zip(r,r[1:])) for r in routes]
            reference.append(dict(source=source,hops=distance,strength=max(products),count=len(routes)))
        assert reference,'No <=3-hop positive control; bounded oracle cannot establish best result'
        distance=min(r['hops'] for r in reference)
        nearest={r['source']:r for r in reference if r['hops']==distance}
        result,elapsed,qid=lookup(con,target,'',threshold)
        assert result['status']=='OK' and result['source_count']==100 and result['team_comparison_complete'],result
        assert {r['source_id'] for r in result['routes']}==set(nearest),result
        for r in result['routes']:
            wanted=nearest[r['source_id']]
            assert r['hops']==wanted['hops'] and r['shortest_route_count']==wanted['count']
            assert math.isclose(r['route_strength'],wanted['strength'],abs_tol=1e-8)
            assert r['route'][0]==r['source_id'] and r['route'][-1]==target
            assert all(g.has_edge(a,b) for a,b in zip(r['route'],r['route'][1:]))
        best=sorted(nearest.values(),key=lambda r:(r['hops'],-r['strength'],r['source']))[0]
        assert result['best_source_id']==best['source']
        report['direct_tests'].append(dict(company=company,title=title,threshold=threshold,result=result,seconds=elapsed,query_id=qid,oracle='Exhaustive NetworkX shortest routes over all edges required for paths <=3 hops from all 100 seeds.'))
        print(f'PASS {company} {title} threshold={threshold}: {elapsed:.2f}s; {len(nearest)} nearest sources',flush=True)
        report_path.write_text(json.dumps(report,indent=2)+'\n')
    report['edge_checks']=expanded_edge_checks(con)
    for (company,title,_,threshold),expected_case in zip(cases,report['direct_tests']):
        question=f'Who among our 100 employees can connect us to the {title} at {company}, and why?'
        if threshold:question+=f' Every individual link must have strength at least {threshold}.'
        response,elapsed=chat(con,question)
        content=[c for c in response.get('content',[]) if c.get('type')!='thinking']
        tool_results=[c['tool_result'] for c in content if c.get('type')=='tool_result' and c['tool_result']['name']=='intro_lookup']
        assert len(tool_results)==1,content
        payload=tool_results[0]['content'][0]['json']
        assert not payload.get('truncated') and tool_results[0]['status']=='success'
        returned=json.loads(payload['result']) if isinstance(payload['result'],str) else payload['result']
        assert returned['best_source_id']==expected_case['result']['best_source_id'] and returned['source_count']==100
        assert returned['min_link_strength']==threshold
        report['agent_tests'].append(dict(question=question,seconds=elapsed,content=content))
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'question':question,'seconds':elapsed,'content':content}),flush=True)
    cur.execute(f'USE ROLE {paths._cfg.ADMIN_ROLE}');cur.execute('USE SECONDARY ROLES ALL')
    assert demo_snapshot(con)==report['original_demo_snapshot']
    report['status']='Direct oracle and Cortex tool-result checks passed; responses saved for review'
    report_path.write_text(json.dumps(report,indent=2)+'\n')


def expanded_edge_checks(con):
    """Check self, isolated, ambiguous and invalid inputs without rebuilding data."""
    results=[]
    for target,source,threshold,status,hops in [
        (experiment.PRIYA,'',0,'OK',0),
        ('SCALE_P000000006','',0,'OK',None),
        ('Avery','',0,'AMBIGUOUS',None),
        (experiment.TARGET,'',1.1,'INVALID_THRESHOLD',None),
        (experiment.TARGET,experiment.DANA,0,'OK',2)]:
        value,seconds,qid=lookup(con,target,source,threshold)
        assert value['status']==status,value
        if hops is not None:assert value['routes'][0]['hops']==hops,value
        if target=='SCALE_P000000006':
            assert value['best_source_id'] is None and value['team_comparison_complete']
            assert len(value['source_summary'])==100
            assert all(r['status']=='unreachable' for r in value['source_summary'])
        results.append(dict(target=target,source=source,threshold=threshold,status=status,seconds=seconds,query_id=qid))
    return results


def revise(con):
    """Revise isolated synthetic facts and install contact tools; no base changes."""
    before=demo_snapshot(con)
    f=experiment.revise_test_data(con)
    cur=con.cursor();cur.execute(f'GRANT SELECT ON TABLE {SCHEMA}.TEAM_MEMBERS TO ROLE {paths._cfg.DEPLOY_ROLE}')
    install_attributes(con)
    assert demo_snapshot(con)==before
    report={'status':'revised; validation pending','fixture_version':2,'seed_count':len(f['seeds']),
        'raw_rows':{k:len(f[k]) for k in ('labels','roles','parties','crm','members')},
        'schema':SCHEMA,'original_demo_snapshot':before,'original_demo_unchanged':True,
        'limitations':['Synthetic demonstration; not calibrated against real professional networks.',
          'The million-person background still uses bounded workplace sizes and synthetic careers.',
          'Current team membership does not generate coworker links; selected historical co-work does.',
          'No refreshed communities and no complete all-team hop histogram.']}
    (ROOT/'artifacts/intro_varied_1m.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def test_revised(con):
    """Validate v2 evidence, complete contact pagination, attributes and natural language."""
    f=experiment.varied_fixture();cur=con.cursor();dest=ROOT/'artifacts/intro_varied_1m.json'
    report=json.loads(dest.read_text())
    def save_report():dest.write_text(json.dumps(report,indent=2,default=str)+'\n')
    def call(name,args):
        started=time.perf_counter()
        raw=cur.execute(f"CALL {SCHEMA}.{name}({','.join(['%s']*len(args))})",args).fetchone()[0]
        return (json.loads(raw) if isinstance(raw,str) else raw),time.perf_counter()-started,cur.sfqid
    expected=experiment.original_oracle(dict(f,roles=f['evidence_roles']))
    actual=cur.execute(f'SELECT P1,P2,MAX(STRENGTH) FROM {SCHEMA}.ADDED_EVIDENCE GROUP BY P1,P2').fetchall()
    assert {(a,b) for a,b,_ in actual}==set(expected)
    for a,b,w in actual:assert math.isclose(float(w),expected[a,b]['strength'],abs_tol=1e-8)
    report['evidence_pairs_validated']=len(actual)
    assert cur.execute(f'SELECT COUNT(*),COUNT(DISTINCT ID) FROM {SCHEMA}.PERSON').fetchone()==(1000000,1000000)
    assert {r[0] for r in cur.execute(f'SELECT PERSON_ID FROM {SCHEMA}.TEAM_SEEDS')}==set(f['seeds'])
    report['team_edges']=cur.execute(f'SELECT COUNT(*)/2 FROM {SCHEMA}.KNOWS_EDGES E JOIN {SCHEMA}.TEAM_SEEDS A ON A.PERSON_ID=E.SRC JOIN {SCHEMA}.TEAM_SEEDS B ON B.PERSON_ID=E.DST').fetchone()[0]
    assert report['team_edges']<100 # Previously the 100-member overlay created 4,950 pairs.
    print('Evidence pairs:',len(actual),'team edges:',report['team_edges'],flush=True)
    cur.execute(f'USE ROLE {paths._cfg.DEPLOY_ROLE}');cur.execute('USE SECONDARY ROLES NONE')
    report['attribute_tests']=[]
    inputs=[('', 'Willow Diagnostics','CEO','current',False,1,20),
            ('','Willow Diagnostics Advisory','Senior Consultant','former',False,1,20),
            ('','Willow Diagnostics','CTO','current',False,1,20),
            ('','','','current',True,1,20)]
    for args in inputs:
        v,seconds,qid=call('SEARCH_PEOPLE',args)
        report['attribute_tests'].append(dict(args=args,result=v,seconds=seconds,query_id=qid))
    target=f['executives']['Willow Diagnostics']['Chief Executive Officer']
    assert {r['person_id'] for r in report['attribute_tests'][0]['result']['matches']}=={target}
    assert all(r['end_date'] and r['end_date']<='2026-10-01' for r in report['attribute_tests'][1]['result']['matches'])
    assert report['attribute_tests'][1]['result']['total_people']==2
    assert report['attribute_tests'][2]['result']['total_people']==0
    assert report['attribute_tests'][3]['result']['total_people']==100
    # Walk all attribute pages, proving the old first-ten limitation is gone.
    page=1;people=set();record_count=0
    while page:
        v,_,_=call('SEARCH_PEOPLE',('','','','current',True,page,50))
        people.update(r['person_id'] for r in v['matches']);record_count+=len(v['matches']);page=v['next_page']
    assert people==set(f['seeds'])
    report['team_attribute_pagination']={'distinct_people':len(people),'role_records':record_count}
    save_report()
    report['contact_tests']=[]
    for minimum,team_only in [(0,False),(0.75,False),(0,True)]:
        ref=cur.execute(f"SELECT E.DST,E.STRENGTH,E.EVIDENCE FROM {SCHEMA}.KNOWS_EDGES E WHERE E.SRC=%s AND E.STRENGTH>=%s"+
            (f' AND EXISTS (SELECT 1 FROM {SCHEMA}.TEAM_SEEDS T WHERE T.PERSON_ID=E.DST)' if team_only else '')+' ORDER BY E.STRENGTH DESC,E.DST',(target,minimum)).fetchall()
        contacts=[];pages=[];page=1
        while page:
            v,seconds,qid=call('PERSON_CONTACTS',(target,minimum,team_only,page,7))
            assert v['status']=='OK' and v['total_contacts']==len(ref),v
            pages.append(dict(page=page,seconds=seconds,query_id=qid));contacts.extend(v['contacts']);page=v['next_page']
        assert [r['person_id'] for r in contacts]==[r[0] for r in ref]
        for r,raw in zip(contacts,ref):
            assert math.isclose(r['strength'],float(raw[1]),abs_tol=1e-8)
            assert r['score_basis']==raw[2] and r['score_basis']
            assert r['on_team']==(r['person_id'] in f['seeds'])
        report['contact_tests'].append(dict(target=target,minimum=minimum,team_only=team_only,total=len(ref),pages=pages,contacts=contacts))
        print(f'PASS contacts threshold={minimum} team_only={team_only}: {len(ref)} across {len(pages)} pages',flush=True)
        save_report()
    for args,status in [((target,0,False,0,20),'INVALID_PAGE'),(('not-a-person-943',0,False,1,20),'NOT_FOUND'),
                        (('SCALE_P000000006',0,False,1,20),'OK')]:
        v,_,_=call('PERSON_CONTACTS',args);assert v['status']==status,v
        if args[0]=='SCALE_P000000006':assert v['total_contacts']==0
    # Prove that the topology no longer forces all 100 employees within two hops.
    one={r[0] for r in cur.execute(f'SELECT DST FROM {SCHEMA}.KNOWS_EDGES WHERE SRC=%s',(target,))}
    two=set(one)
    if one:
        two.update(r[0] for r in cur.execute(f"SELECT DISTINCT DST FROM {SCHEMA}.KNOWS_EDGES WHERE SRC IN ({','.join(['%s']*len(one))})",sorted(one)))
    report['willow_team_within_two_hops']=len(two & set(f['seeds']))
    report['willow_team_not_within_two_hops']=len(set(f['seeds'])-two-{target})
    assert report['willow_team_not_within_two_hops']>0
    intro,seconds,qid=lookup(con,target,'',0)
    assert intro['status']=='OK' and intro['source_count']==100,intro
    report['introduction_check']={'result':intro,'seconds':seconds,'query_id':qid}
    questions=[
        'Who is the CEO of Willow Diagnostics?',
        'Show everyone directly connected to the CEO of Willow Diagnostics, including people outside our team, with relationship strengths and why. Retrieve all pages.',
        'Show the CEO of Willow Diagnostics contacts with strength at least 0.75, including people outside our team.',
        'Who formerly worked at Willow Diagnostics Advisory as a Senior Consultant?']
    report['agent_tests']=[]
    for question in questions:
        response,seconds=chat(con,question)
        content=[c for c in response.get('content',[]) if c.get('type')!='thinking']
        assert any(c.get('type')=='text' for c in content),content
        for c in content:
            if c.get('type')=='tool_result':
                assert c['tool_result']['status']=='success',c
                assert not c['tool_result']['content'][0]['json'].get('truncated'),c
        report['agent_tests'].append(dict(question=question,seconds=seconds,content=content))
        save_report()
        print(json.dumps({'question':question,'seconds':seconds,'answer':[c.get('text') for c in content if c.get('type')=='text']}),flush=True)
    cur.execute(f'USE ROLE {paths._cfg.ADMIN_ROLE}');cur.execute('USE SECONDARY ROLES ALL')
    assert demo_snapshot(con)==report['original_demo_snapshot']
    report['status']='Direct checks passed; Cortex answers saved for review';save_report()



def rai_tools_initializer():
    """Package only the validated RAI route query; no model refresh or engine management.

    Returns a self-contained SDK initializer. Credentials/config files are never
    packaged. The Snowflake procedure uses its caller's active Snowpark session.
    Existing find_people and person_contacts tools are retained at agent handoff.
    """
    source_schema, base_schema, engine = SCHEMA, BASE, paths._cfg.ENGINE

    def init_tools():
        from relationalai.config.config import ConfigFromActiveSession
        from relationalai.agent.cortex import QueryCatalog, ToolRegistry
        from pe_deal_graph.intro_rai import IntroductionModel, configuration
        try:
            from snowflake.snowpark.context import get_active_session
            get_active_session()
        except Exception:
            cfg = configuration()  # local preflight only, never packaged credentials
        else:
            cfg = ConfigFromActiveSession(reasoners={'logic': {'name': engine}},
                                          data={'query_timeout_mins': 5, 'poll_timeout_mins': 6})
            cfg.model.path = None
            cfg.oplog.enabled = False
            cfg.deployment = None
        cfg.reasoners.logic.name = engine
        base_model = IntroductionModel(cfg, source_schema=source_schema, base_schema=base_schema)

        def introduction_routes(target_id: str, source_id: str = '', min_strength: float = 0.,
                                max_hops: int = 12, page_number: int = 1, page_size: int = 5):
            """Compute strongest shortest introduction routes in RAI using resolved person IDs.

            Resolve company/title/name with find_people first. Empty source_id compares
            all 100 team members. min_strength filters each link, not the route product.
            Rank by fewest hops then highest product. Each source has one deterministic
            best witness, not a list of all tied routes. Results are paginated, with total
            sources and next_page. Self is zero hops; unreachable is explicit. A reachable
            source beyond max_hops has a distance but no route/score. No engine is resumed.
            Synthetic facts as of 2026-10-01. Scores are heuristics, not probabilities.
            """
            if type(page_number) is not int or page_number < 1 or type(page_size) is not int or not 1 <= page_size <= 5:
                raise ValueError('page_number must be positive and page_size must be 1–5')
            model = base_model if min_strength == 0 else IntroductionModel(
                cfg, min_strength=min_strength, source_schema=source_schema, base_schema=base_schema)
            result = model.routes(target_id, source_id, max_hops)
            total = len(result)
            valid = result[result['hops'] >= 0]
            if len(valid):
                first = valid.iloc[0]
                tied = (result['hops'] == first['hops']) & ((result['product_strength'] - first['product_strength']).abs() <= 1e-12)
                result['is_best'] = tied
                result['best_tie_count'] = int(tied.sum())
            else:
                result['is_best'] = False
                result['best_tie_count'] = 0
            start = (page_number - 1) * page_size
            if start >= total:
                raise ValueError(f'Page is outside the {total} source results')
            page = result.iloc[start:start+page_size].copy()
            page['rank'] = list(range(start+1, start+len(page)+1))
            page['total_sources'] = total
            page['next_page'] = page_number + 1 if start + len(page) < total else None
            page.loc[page['hops'] < 0, 'hops'] = None
            page.loc[page['product_strength'] < 0, 'product_strength'] = None
            from relationalai.agent.cortex.response_envelope import shape_tool_response
            if shape_tool_response(page.to_dict('records'), kind='tabular')['truncated']:
                raise ValueError('Evidence exceeds tool size limit; retry with a smaller page_size')
            return page

        return ToolRegistry().add(model=base_model.model,
                                 description='Synthetic enriched PE introductions; RAI graph distance and route scoring.',
                                 queries=QueryCatalog(introduction_routes))
    return init_tools

def prepare_native_rai_tools():
    """Install only PE_NATIVE test procedures; never switch an agent or manage engines."""
    import zipfile
    from pe_deal_graph.intro_rai import configuration
    from relationalai.agent.cortex import CortexToolResources, DeploymentConfig
    from relationalai.agent.cortex.api.agent import CortexAgentApi
    build = ROOT / 'build/intro_rai_agent'
    build.mkdir(parents=True, exist_ok=True)
    archive = build / 'pe_intro_rai.zip'
    # Explicit module list: never package credentials or the whole working folder.
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in ['__init__.py', 'intro_rai.py', 'settings.py', 'communities.py']:
            bundle.write(ROOT / 'pe_deal_graph' / name, 'pe_deal_graph/' + name)
    database, schema = SCHEMA.split('.')
    session = configuration().get_session()
    config = DeploymentConfig(agent_name='PE_INTRO_1M_TEST', database=database,
        schema=schema, warehouse=paths._cfg.WAREHOUSE, prefix='PE_NATIVE',
        stage_name='PE_NATIVE_SPROCS', allow_preview=True, query_timeout_s=300)
    resources = CortexToolResources(session, database=database, schema=schema,
                                   prefix='PE_NATIVE', stage_name='PE_NATIVE_SPROCS')
    base = CortexAgentApi.AgentSpec.from_dict({'name': 'PE_INTRO_1M_TEST',
                                              'models': {'orchestration': 'auto'}})
    # Match this Snowflake Python runtime's preloaded telemetry namespace.
    spec = resources.create(init_tools=rai_tools_initializer(), imports=[str(archive)],
        config=config, agent_spec=base, extra_packages=['opentelemetry-api==1.38.0',
        'opentelemetry-sdk==1.38.0', 'opentelemetry-semantic-conventions==0.59b0'])
    result = spec.to_dict()
    (ROOT / 'artifacts/intro_rai_tool_spec.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def native_rai_specification(current, native_tools):
    """Replace only this test agent's route tool; preserve attribute/contact tools."""
    import copy
    spec = copy.deepcopy(current)
    keep = {'find_people', 'person_contacts'}
    spec['tools'] = [t for t in spec['tools'] if t['tool_spec']['name'] in keep] + native_tools['tools']
    spec['tool_resources'] = {k: v for k, v in spec['tool_resources'].items() if k in keep}
    spec['tool_resources'].update(native_tools['tool_resources'])
    spec['orchestration'] = {'budget': {'seconds': 600, 'tokens': 12000}}
    spec['instructions']['orchestration'] = (
        'Synthetic enriched 1M PE experiment, as of 2026-10-01. Use tools for all factual answers. '
        'Resolve person/company/title/current or former employment with find_people before route lookup. '
        'Use returned IDs, never invented IDs. Distinguish absent company or role from unreachable. '
        'If multiple people match, clarify unless the user explicitly asks to compare all. '
        'For introductions and person-to-person routes use RAI_DISCOVER_MODELS, then RAI_QUERY_MODEL '
        'with the discovered model ID and catalog query introduction_routes. The arg2 JSON is '
        '{"id":"introduction_routes","args":{"target_id":"resolved ID","source_id":"",'
        '"min_strength":0,"max_hops":12,"page_number":1,"page_size":3}}. '
        'Empty source_id compares all 100 team members; for a named source resolve its ID first. '
        'min_strength applies to every edge, not the product. Default 0 unless requested. '
        'RAI computes distances and best-product shortest routes on demand. One deterministic witness '
        'per source is returned; do not claim it enumerates all equal routes. Rank hops first then '
        'product. total_sources counts all compared sources; next_page indicates undisplayed rows. '
        'Report all best-source ties using best_tie_count; fetch further pages if needed. '
        'Do not call three displayed rows all team results. Beyond-cap is not unreachable. '
        'For contact exploration use person_contacts, team_only=false unless requested; resolve '
        'attributes first and follow next_page to fulfill requests for everyone. Direct-contact tools '
        'read existing saved connections; only introduction routes invoke native RAI graph search. '
        'Respect errors and truncation; never substitute old demo facts or infer missing routes. '
        'Community outputs have not been refreshed for this enriched graph; do not present old scores. '
        'Return concise routes, hops, product and dated link evidence. Scores are heuristics, not '
        'probabilities or guaranteed introductions. Do not infer familiarity from employment alone.'
    )
    spec['instructions']['sample_questions'] = [
        {'question': 'Who can connect us to the CEO of Willow Diagnostics, and why?'},
        {'question': 'Show everyone directly connected to the CEO of Willow Diagnostics.'},
    ]
    return spec


if __name__=='__main__':main()
