"""Deploy/update the isolated dynamic PyRel Cortex agent and run live chat tests."""
from pathlib import Path
import argparse,hashlib,json,re,time,zipfile
from scripts.person_path_proc import connect
from pe_deal_graph import settings
from .dynamic import EXAMPLE

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=settings.schema('CORPORATE_AGENT')
AGENT=SCHEMA+'.CORPORATE_INTRODUCTIONS'


def spec():
    guidance='''You help Northwind Equity Partners identify employment-backed introduction candidates.
Internal data context: facts are fictional as of 2026-10-01. "Our team" is the separate 100-person PE firm. CEO is an original role; Head of Data is a supplemental synthetic designation. Keep this provenance available when asked; do not append routine data disclaimers to business answers.
Always resolve names, company and roles using find_people first and use the returned IDs. Ask for clarification on ambiguous matches; never invent people or leaders.
For EVERY connection/introduction question AUTHOR a read-only PyRel query and send it to execute_pyrel. Never answer connectivity from lookup, memory or prior conversation. target_id is the destination; source_id is empty for our team or the resolved named source for X-to-Y.
Available bindings: model, Person, graph, center, Sources, best_route, shortest_route, Integer, Float, String. The query MUST invoke graph.distance(from_=center), join its output with Sources and best_route (or shortest_route when fewest hops is explicitly requested), and select every alias shown in the example. Assign it to query. Do not import, use SQL, perform IO, define functions/rules or call to_df: the tool executes the query.
Default to the strongest product across simple paths of ONE, TWO or THREE edges, then fewer hops and a deterministic witness. Bind graph.distance to minimum_hops separately from selected route hops: a stronger multi-hop route may coexist with a weaker direct edge. Include minimum_hops <= 3 and hops <= 3. A selected three-hop route has TWO intermediaries, both of whom must appear in the explanation. A selected route is one witness per source, not all routes or the only possible route. Only minimum_hops > 1 supports saying no qualifying direct link was found. An empty result means no route within three hops under the requested filters, not global disconnection.
RAI calculates all scores. raw_strength preserves the approved formula: effective years=sum of unioned shared days × location × recency / 365.25; raw edge=.5×min(effective years/mean complete career years,1)+.5×min(effective years/10,1)^2. Location: same known onsite office 1; same known onsite city .6; other/remote/unknown .25. Recency: 0–2 years 1, 2–5 .8, 5–10 .5, 10–15 .25, older .1. Shared employment requires >=365 days. Union intervals avoid double counting. Friendship is deferred, current PE co-employment alone creates no edges, and centrality adds no score bonus.
Public strength=sqrt(sqrt(raw_strength)), a FIXED 0–1 normalization preserving ranks and products. Apply requested cutoffs to strength unless raw is explicitly requested. Select BOTH strength and raw_strength. Normalized leg scores multiply to normalized route score; raw contributions sum only to raw_strength. Do not change or invent scores. Explain the math, raw values and scale caveats only when asked.
edge_details contains native evidence; decode arrays with edge_detail_columns when present and merge edge_detail_constants into each decoded edge. Full periods remain in QUERY_AUDIT.RESULT. Use representative employment as examples if other periods also contribute. Never infer reasons for an undisplayed person's ranking. network_context covers only the 2,100-person PE/CEO/Head-of-Data cohort: weighted Louvain uses RAW weights; betweenness is exact unweighted on cohort edges above raw .02666666666666667. Discuss these metrics and their scope only when requested; missing metrics are not zero.
Use top_n=5 unless another count is requested (maximum 10). total_connections counts starting PEOPLE, not paths. If displayed < total_connections, label the table top results. No gender facts are supplied: use names or they/them. Employment records support potential introductions; never invent actual friendship, willingness, certainty, or inability to introduce. If the tool errors because of syntax, correct the query once. For a timeout or engine failure, report it and do not retry automatically. Never fabricate success or substitute another backend. Do not offer scheduling, outreach or other actions unavailable through your tools.
Follow the response instructions for natural writing, bold recommendations and execution references.
Example valid PyRel (adapt filters to the request):
'''+EXAMPLE
    tools=[{'tool_spec':{'type':'generic','name':'find_people',
       'description':'Resolve corporate/PE people by name or ID, current company, role, or explicit synthetic Head of Data designation. Provides PyRel query reference. No graph calculation.',
       'input_schema':{'type':'object','properties':{k:{'type':'string','description':d} for k,d in
         [('person','Name fragment or exact person ID, empty if unspecified'),('company','Company name fragment or ID, empty if unspecified'),('title','Current title/role, CEO, CFO, or Head of Data; empty if unspecified')]}|{'team_only':{'type':'boolean','description':'Restrict lookup to the separate 100-person PE firm team'}},
         'required':['person','company','title','team_only']}}},
      {'tool_spec':{'type':'generic','name':'execute_pyrel',
       'description':'Execute agent-authored read-only PyRel with native RAI graph.distance and employment/path rules. Every call is live and audited. Supports exact introduction paths with one, two or three edges.',
       'input_schema':{'type':'object','properties':{
        'target_id':{'type':'string','description':'Resolved destination ID from find_people'},
        'source_id':{'type':'string','description':'Empty for our 100 PE employees, or resolved named source ID'},
        'pyrel_code':{'type':'string','description':'Actual PyRel code authored for this request, including graph.distance(from_=center) and query=model.where(...).select(...). Use the example and required columns from instructions.'},
        'top_n':{'type':'integer','description':'1–10 displayed connections; default 5'}},
        'required':['target_id','source_id','pyrel_code','top_n']}}}]
    return {'models':{'orchestration':'auto'},'orchestration':{'budget':{'seconds':600,'tokens':16000}},
       'instructions':{'orchestration':guidance,'response':'''Answer only from successful tool results. Start with the recommended starting person's name in **bold**, followed by a concise, evidence-based reason to approach that person. Say "strongest route found" or "a possible introduction via"; do not promise access or imply a personal relationship is confirmed.
Return Connection | Target | Hops | Strength (normalized) | Reason. Bold the starting person's name in the Connection column and retain the person ID. Use normalized strength to four decimals, with more significant digits if needed so a nonzero score is not rounded to zero. Never substitute raw_strength.
Write Reason as one or two natural sentences using each person's name and the dated employer overlap for EVERY edge. For three hops, name BOTH intermediaries and explain all three links. Describe same-office or same-city evidence naturally when present; omit repetitive missing-office statements. Example style: "Eamon worked with Fiona at Willowmont Retail Group from 2013 to 2017. Fiona later shared an office with Malik at Aspenview Materials from 2019 to 2026." Do not write "Leg 1", "Leg 2", "Leg 3", raw field names, calculation dumps or per-edge numeric scores unless asked for a breakdown. Preserve the source facts; do not invent exact dates, titles, familiarity or willingness. Representative periods may be introduced with "For example" when they are only part of the evidence.
By default OMIT any Limits, Limitations, Caveats or Disclaimer section. Do not append boilerplate about fictional data, as-of date, non-probability, uncertain familiarity, or the hop cap. Explain these accurately if the user asks about assumptions, methodology or limitations. An empty result should still say "No qualifying route found within three hops" (and mention an explicitly requested cutoff); report real execution failures clearly. No qualifying link is not proof someone cannot introduce another person.
Keep network centrality/community and scoring mechanics out of default introduction answers. Do not infer absent people's routes from aggregate counts. Describe total_connections as starting people, never the number of routes. Use names or gender-neutral pronouns. Do not claim a selected witness is the only possible route.
End with a compact execution reference containing request_id and the native RAI transaction IDs exactly as returned. Keep generated code out of the default business answer. Never present an unexecuted query as a result.''',
         'sample_questions':[{'question':'Who can introduce us to the CEO of Aspenview Materials?'},{'question':'Who on our team is connected to the head of data of Aspenview Materials?'}]},
       'tools':tools,'tool_resources':{name:{'type':'procedure','identifier':SCHEMA+'.'+proc,
           'execution_environment':{'type':'warehouse','warehouse':settings.WAREHOUSE,'query_timeout':600 if name=='execute_pyrel' else 120}}
           for name,proc in [('find_people','FIND_PEOPLE'),('execute_pyrel','EXECUTE_PYREL')]}}


def deploy():
    package=ROOT/'corporate_agent'
    files=['__init__.py','model.py','scoring.py','presentation.py','dynamic.py','runtime.py']
    digest=hashlib.sha256(b''.join((package/p).read_bytes() for p in files)).hexdigest()
    archive=ROOT/f'build/corporate_agent_{digest[:16]}.zip'
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.write(package/p,'corporate_agent/'+p)
        z.writestr('corporate_agent/_build.py',f'RUNTIME_SHA256 = {digest!r}\n')
    with connect() as con:
        c=con.cursor()
        c.execute(f'ALTER TABLE {SCHEMA}.QUERY_AUDIT ADD COLUMN IF NOT EXISTS RUNTIME_SHA256 VARCHAR')
        c.execute(f'ALTER TABLE {SCHEMA}.QUERY_AUDIT ADD COLUMN IF NOT EXISTS SNOWFLAKE_SESSION_ID NUMBER')
        c.execute(f"PUT 'file://{archive}' @{SCHEMA}.RUNTIME AUTO_COMPRESS=FALSE OVERWRITE=FALSE")
        runtime=f'''RETURNS VARIANT LANGUAGE PYTHON RUNTIME_VERSION='3.13'
          ARTIFACT_REPOSITORY=snowflake.snowpark.pypi_shared_repository
          PACKAGES=('relationalai==1.38.0','opentelemetry-api==1.38.0','opentelemetry-sdk==1.38.0',
            'opentelemetry-semantic-conventions==0.59b0','snowflake-snowpark-python==1.55.3')
          IMPORTS=('@{SCHEMA}.RUNTIME/{archive.name}')
          EXTERNAL_ACCESS_INTEGRATIONS=(S3_RAI_INTERNAL_BUCKET_EGRESS_INTEGRATION)
          HANDLER='run' EXECUTE AS CALLER'''
        c.execute(f'''CREATE OR REPLACE PROCEDURE {SCHEMA}.FIND_PEOPLE(PERSON VARCHAR,COMPANY VARCHAR,TITLE VARCHAR,TEAM_ONLY BOOLEAN)
          {runtime} AS $$
from corporate_agent.runtime import find_people
def run(session,person,company,title,team_only):
    return find_people(session,person,company,title,team_only)
$$''')
        c.execute(f'''CREATE OR REPLACE PROCEDURE {SCHEMA}.EXECUTE_PYREL(TARGET_ID VARCHAR,SOURCE_ID VARCHAR,PYREL_CODE VARCHAR,TOP_N NUMBER)
          {runtime} AS $$
from corporate_agent.runtime import execute_pyrel
def run(session,target_id,source_id,pyrel_code,top_n):
    return execute_pyrel(session,target_id,source_id,pyrel_code,top_n)
$$''')
        c.execute(f"SHOW AGENTS LIKE 'CORPORATE_INTRODUCTIONS' IN SCHEMA {SCHEMA}")
        if c.fetchall():
            c.execute(f'ALTER AGENT {AGENT} MODIFY LIVE VERSION SET SPECIFICATION=$$ {json.dumps(spec())} $$')
        else:
            c.execute(f'''CREATE AGENT {AGENT} COMMENT='Dynamic PyRel + native RAI: isolated corporate PE introduction agent'
                PROFILE='{{"display_name":"Corporate PE Introductions — Dynamic RAI"}}' FROM SPECIFICATION $$ {json.dumps(spec())} $$''')
        for sql in [f'GRANT USAGE ON SCHEMA {SCHEMA} TO ROLE {settings.DEPLOY_ROLE}',
                    f"GRANT USAGE ON SCHEMA {settings.schema('CORPORATE_1M_SRC')} TO ROLE {settings.DEPLOY_ROLE}",
                    *[f"GRANT SELECT ON TABLE {settings.schema('CORPORATE_1M_SRC')}.{table} TO ROLE {settings.DEPLOY_ROLE}"
                      for table in ['PERSON','COMPANY','ROLE_HISTORY']],
                    f'GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO ROLE {settings.DEPLOY_ROLE}',
                    f'GRANT SELECT ON ALL VIEWS IN SCHEMA {SCHEMA} TO ROLE {settings.DEPLOY_ROLE}',
                    f'GRANT USAGE ON ALL PROCEDURES IN SCHEMA {SCHEMA} TO ROLE {settings.DEPLOY_ROLE}',
                    f'GRANT USAGE ON AGENT {AGENT} TO ROLE {settings.DEPLOY_ROLE}',
                    f'GRANT INSERT,UPDATE ON TABLE {SCHEMA}.QUERY_AUDIT TO ROLE {settings.DEPLOY_ROLE}']:
            c.execute(sql)
    report={'agent':AGENT,'runtime_archive':archive.name,'runtime_sha256':digest,'specification':spec()}
    (ROOT/'artifacts/corporate_agent_deployment.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Deployed',AGENT,flush=True)


def chat(question,out,role=None):
    from relationalai.agent.cortex.api.client import http_client
    db,schema,name=AGENT.split('.')
    with connect() as con:
        if role:
            if not re.fullmatch(r'[A-Z0-9_]+',role):raise ValueError('Invalid role')
            con.cursor().execute(f'USE ROLE {role}')
            con.cursor().execute('USE SECONDARY ROLES NONE')
        client=http_client(con,timeout=1000)
        start=time.monotonic()
        response=client.post(f'/api/v2/databases/{db}/schemas/{schema}/agents/{name}:run',
           json={'stream':False,'messages':[{'role':'user','content':[{'type':'text','text':question}]}]})
        if not response.ok:
            Path(out).write_text(json.dumps({'question':question,'http_status':response.status_code,'error':response.text},indent=2)+'\n')
            raise RuntimeError(f'Agent HTTP {response.status_code}: {response.text[:4000]}')
        result=response.json()
    Path(out).write_text(json.dumps({'question':question,'role':role,'seconds':time.monotonic()-start,'response':result},indent=2)+'\n')
    print('Saved',out,flush=True)
    for block in result.get('content',[]):
        if block.get('type')=='text':print(block.get('text'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['deploy','chat']);parser.add_argument('--question');parser.add_argument('--out',default='artifacts/corporate_agent_chat.json');parser.add_argument('--role')
    args=parser.parse_args()
    if args.command=='deploy':deploy()
    else:chat(args.question,args.out,args.role)
