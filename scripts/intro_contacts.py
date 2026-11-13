"""Paginated attribute and direct-contact reads for the isolated introduction agent."""
from __future__ import annotations

READ_JS = r'''
function read(sql,binds){var rs=snowflake.execute({sqlText:sql,binds:binds||[]}),out=[];
 while(rs.next()){var r={};for(var i=1;i<=rs.getColumnCount();i++)r[rs.getColumnName(i).toLowerCase()]=rs.getColumnValue(i);out.push(r);}return out;}
function resolve(value){
 value=String(value||'').trim();if(!value)return {status:'PERSON_REQUIRED'};
 var rows=read('SELECT ID,NAME FROM __SCHEMA__.PERSON WHERE UPPER(ID)=UPPER(?) OR LOWER(NAME)=LOWER(?) ORDER BY ID LIMIT 21',[value,value]);
 if(!rows.length)rows=read('SELECT ID,NAME FROM __SCHEMA__.PERSON WHERE CONTAINS(LOWER(NAME),LOWER(?)) ORDER BY ID LIMIT 21',[value]);
 if(rows.length!==1)return {status:rows.length?'AMBIGUOUS':'NOT_FOUND',matches:rows.slice(0,20),more_matches:rows.length>20};
 return {status:'OK',person:rows[0]};
}
var page=Number(PAGE_NUMBER),size=Number(PAGE_SIZE);
if(!Number.isInteger(page)||page<1||page>100000||!Number.isInteger(size)||size<1||size>50)
 return {status:'INVALID_PAGE',detail:'Page starts at 1; page size must be 1–50.'};
'''


def attribute_sql(schema):
    body=READ_JS+r'''
var name=String(PERSON_NAME||'').trim(), company=String(COMPANY||'').trim(),title=String(TITLE||'').trim();
var employment=String(EMPLOYMENT||'current').toLowerCase();
if(['current','former','any'].indexOf(employment)<0)return {status:'INVALID_EMPLOYMENT'};
if(!name&&!company&&!title&&!TEAM_ONLY)return {status:'FILTER_REQUIRED',detail:'Supply a name, company, title or team-only filter.'};
var aliases={ceo:'Chief Executive Officer',cfo:'Chief Financial Officer',coo:'Chief Operating Officer',cto:'Chief Technology Officer'};
var expanded=aliases[title.toLowerCase()]||title;
var filter=" (?='' OR CONTAINS(LOWER(A.NAME),LOWER(?)) OR UPPER(A.PERSON_ID)=UPPER(?))"+
 " AND (?='' OR CONTAINS(LOWER(A.ORGANIZATION),LOWER(?)) OR UPPER(A.ORG_ID)=UPPER(?))"+
 " AND (?='' OR CONTAINS(LOWER(A.TITLE),LOWER(?)) OR LOWER(A.ROLE_TYPE)=LOWER(?) OR CONTAINS(LOWER(A.TITLE),LOWER(?)))"+
 " AND A.START_DATE<='2026-10-01'::DATE"+
 (employment==='current'?" AND (A.END_DATE IS NULL OR A.END_DATE>'2026-10-01'::DATE)":employment==='former'?" AND A.END_DATE<='2026-10-01'::DATE":"")+
 (TEAM_ONLY?' AND EXISTS (SELECT 1 FROM __SCHEMA__.TEAM_SEEDS S WHERE S.PERSON_ID=A.PERSON_ID)':'');
// Expand acronyms before substring matching: CTO must not match direCTOr.
var binds=[name,name,name,company,company,company,title,expanded,title,expanded];
var query='SELECT DISTINCT A.PERSON_ID,A.NAME,A.ORG_ID,A.ORGANIZATION,A.ROLE_TYPE,A.TITLE,TO_VARCHAR(A.START_DATE) START_DATE,TO_VARCHAR(A.END_DATE) END_DATE FROM __SCHEMA__.PERSON_ATTRIBUTES A WHERE '+filter;
var counts=read('SELECT COUNT(*) N,COUNT(DISTINCT PERSON_ID) PEOPLE FROM ('+query+')',binds)[0];
var matches=read(query+' ORDER BY PERSON_ID,ORG_ID,TITLE,START_DATE,END_DATE LIMIT '+size+' OFFSET '+((page-1)*size),binds);
return {status:counts.n?'MATCHES':'NO_MATCHING_ATTRIBUTES',as_of:'2026-10-01',employment:employment,
 total_role_records:counts.n,total_people:counts.people,page:page,page_size:size,matches:matches,
 next_page:page*size<counts.n?page+1:null,
 detail:'Pages contain matching role records; a person may have multiple roles. Use returned person IDs for contacts or introductions. No match is not evidence of disconnection.'};
'''
    return f'''CREATE OR REPLACE PROCEDURE {schema}.SEARCH_PEOPLE(PERSON_NAME VARCHAR, COMPANY VARCHAR, TITLE VARCHAR,
    EMPLOYMENT VARCHAR, TEAM_ONLY BOOLEAN, PAGE_NUMBER FLOAT, PAGE_SIZE FLOAT)
    RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS CALLER AS $$
    {body.replace('__SCHEMA__',schema)}
    $$'''


def contacts_sql(schema):
    body=READ_JS+r'''
var person=resolve(PERSON);if(person.status!=='OK')return person;
var minimum=Number(MIN_STRENGTH);
if(MIN_STRENGTH===null||!isFinite(minimum)||minimum<0||minimum>1)return {status:'INVALID_THRESHOLD'};
var filter=' E.SRC=? AND E.STRENGTH>=?'+(TEAM_ONLY?' AND EXISTS (SELECT 1 FROM __SCHEMA__.TEAM_SEEDS S WHERE S.PERSON_ID=E.DST)':'');
var total=read('SELECT COUNT(*) N FROM __SCHEMA__.KNOWS_EDGES E WHERE '+filter,[person.person.id,minimum])[0].n;
var contacts=read('SELECT E.DST PERSON_ID,P.NAME,E.STRENGTH,E.EVIDENCE SCORE_BASIS,EXISTS(SELECT 1 FROM __SCHEMA__.TEAM_SEEDS S WHERE S.PERSON_ID=E.DST) ON_TEAM FROM __SCHEMA__.KNOWS_EDGES E JOIN __SCHEMA__.PERSON P ON P.ID=E.DST WHERE '+filter+' ORDER BY E.STRENGTH DESC,E.DST LIMIT '+size+' OFFSET '+((page-1)*size),[person.person.id,minimum]);
if(contacts.length){
 var ids=contacts.map(function(c){return c.person_id;}),marks=ids.map(function(){return '?';}).join(',');
 var roles=read('SELECT PERSON_ID,TITLE,ORGANIZATION,TO_VARCHAR(START_DATE) START_DATE,TO_VARCHAR(END_DATE) END_DATE FROM __SCHEMA__.PERSON_ATTRIBUTES WHERE PERSON_ID IN ('+marks+") AND START_DATE<='2026-10-01'::DATE AND (END_DATE IS NULL OR END_DATE>'2026-10-01'::DATE) ORDER BY PERSON_ID,ORG_ID,TITLE",ids);
 var evidence=read('SELECT P1,P2,KIND,STRENGTH,EVIDENCE FROM __SCHEMA__.ADDED_EVIDENCE WHERE (P1=? AND P2 IN ('+marks+')) OR (P2=? AND P1 IN ('+marks+')) ORDER BY P1,P2,STRENGTH DESC',[person.person.id].concat(ids,[person.person.id],ids));
 var deals=read('SELECT A.TRANSACTION_ID,A.PARTY_ROLE TARGET_ROLE,B.LEAD_PERSON_ID CONTACT_ID,B.PARTY_ROLE CONTACT_ROLE,TO_VARCHAR(A.CLOSE_DATE) CLOSE_DATE FROM __SCHEMA__.DEAL_PARTY A JOIN __SCHEMA__.DEAL_PARTY B ON A.TRANSACTION_ID=B.TRANSACTION_ID WHERE A.LEAD_PERSON_ID=? AND B.LEAD_PERSON_ID IN ('+marks+') ORDER BY A.TRANSACTION_ID,B.LEAD_PERSON_ID',[person.person.id].concat(ids));
 contacts.forEach(function(c){c.deal_evidence=deals.filter(function(d){return d.contact_id===c.person_id;}).map(function(d){return {transaction_id:d.transaction_id,close_date:d.close_date,participants:[{person_id:person.person.id,name:person.person.name,role:d.target_role},{person_id:c.person_id,name:c.name,role:d.contact_role}]};});c.current_roles=roles.filter(function(r){return r.person_id===c.person_id;});
   c.additional_evidence=evidence.filter(function(e){return e.p1===c.person_id||e.p2===c.person_id;});});
}
return {status:'OK',person:person.person,as_of:'2026-10-01',scope:TEAM_ONLY?'direct contacts on our team':'all direct contacts, including outside our team',
 min_strength:minimum,total_contacts:total,page:page,page_size:size,contacts:contacts,
 next_page:page*size<total?page+1:null,
 note:'These are one-hop modeled relationships, not proof of familiarity. Strength is the maximum evidence score, not a probability. score_basis supports the selected strength; additional_evidence can have lower scores. Dates are as of 2026-10-01.'};
'''
    return f'''CREATE OR REPLACE PROCEDURE {schema}.PERSON_CONTACTS(PERSON VARCHAR, MIN_STRENGTH FLOAT,
        TEAM_ONLY BOOLEAN, PAGE_NUMBER FLOAT, PAGE_SIZE FLOAT)
        RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS CALLER AS $$
        {body.replace('__SCHEMA__',schema)}
        $$'''


def configure(spec,schema,warehouse):
    spec['tools']=[t for t in spec['tools'] if t['tool_spec']['name']!='find_people']
    fields={
        'person_name':{'type':'string','description':'Name fragment or exact person ID; empty if not specified.'},
        'company':{'type':'string','description':'Company name fragment or ID; empty if unspecified.'},
        'title':{'type':'string','description':'Job title/role fragment, including CEO or CFO; empty if unspecified.'},
        'employment':{'type':'string','enum':['current','former','any'],'description':'Default current; former requires ended employment; any includes both.'},
        'team_only':{'type':'boolean','description':'True only when restricting to our 100 employees.'},
        'page_number':{'type':'number','description':'1-based page. Follow next_page for more; never invent a complete result from one page.'},
        'page_size':{'type':'number','description':'1–50, default 20.'}}
    contact_fields={
        'person':{'type':'string','description':'Person ID obtained from find_people, or name. Resolve company/title first.'},
        'min_strength':{'type':'number','description':'Minimum direct-link strength, 0 to 1; default 0.'},
        'team_only':{'type':'boolean','description':'Default FALSE: show all contacts, not only team members. True only if explicitly requested.'},
        'page_number':fields['page_number'],'page_size':fields['page_size']}
    for name,description,props,proc in [
        ('find_people','Search people by name, company, job title, current/former employment and team membership, with complete pagination.',fields,'SEARCH_PEOPLE'),
        ('person_contacts','List EVERY direct contact of a person through pages: names, roles, strengths and relationship evidence. Includes people outside our team by default.',contact_fields,'PERSON_CONTACTS')]:
        spec['tools'].append({'tool_spec':{'type':'generic','name':name,'description':description,
            'input_schema':{'type':'object','properties':props,'required':list(props)}}})
        spec['tool_resources'][name]={'type':'procedure','identifier':schema+'.'+proc,
            'execution_environment':{'type':'warehouse','warehouse':warehouse,'query_timeout':90}}
    # Replace obsolete parameter instructions as well as the five/nearest-only mental model.
    spec['instructions']['orchestration']=(
        'This is a synthetic enriched 1M test, as of 2026-10-01. Use tools for every data-specific answer. '
        'First distinguish the intent: INTRODUCTION (who on our team can connect us) uses intro_lookup; '
        'CONTACT EXPLORATION (who is connected to this person, their contacts, relationship strengths and why) uses person_contacts with team_only=false unless explicitly restricted. '
        'Do not substitute nearest-team introduction results for a contact list. '
        'Resolve company/title or other attributes with find_people before either tool. Use person_name, company, title, employment=current/former/any, team_only, page_number and page_size. '
        'Default empty name/company/title filters, employment=current, team_only=false, page_number=1,page_size=20. '
        'For former employment use former, not any. Search filters combine with AND. Resolve the records yourself; do not ask the user to supply the CEO name. '
        'If multiple distinct people match, show choices instead of guessing. Role records can repeat a person. '
        'Use next_page for pagination and report the total and range displayed. Never claim to show everyone while next_page is non-null. '
        'When asked for everyone, retrieve all pages if the result fits the response budget; otherwise show a page, disclose the total and offer the next page. '
        'For introduction queries use source_person empty to consider all 100 seeds; nearest-layer results do not contain other employees distances. '
        'Named-source routes use source_person. A person_contacts result describes direct, one-hop connections only. '
        'Do not answer a request for more-than-two-hop people with two-hop examples, or infer a complete team-distance distribution from partial checks. '
        'Explain that full-team hop filtering is not supplied by these tools; named-source routes remain available. '
        'Use strength threshold zero unless specified; intro_lookup min_link_strength and person_contacts min_strength are per-edge scores. '
        'Not found, ambiguous, beyond-hop-limit and search-limit states are not disconnection. No communities or centrality were refreshed. '
        'Only these read tools are available; no writes, graph refreshes or engine changes.')
    spec['instructions']['response']=(
        'Be concrete and concise. Attribute searches show matched people, job/company and employment dates. '
        'Contact questions show name, current role/company, link strength and the actual score_basis evidence in a table. '
        'Show the target name and the total contact count. Disclose pagination with rows shown and remaining; never hide truncation. '
        'Use plain descriptions of employment overlap, CRM and deal evidence; preserve dates. Do not infer coworkers are personal acquaintances. '
        'For introductions name the best route under the model, hops and product strength; rank fewest hops first then strength, preserve ties. '
        'Do not present the best introduction as every contact. Do not call model scores probabilities or actual familiarity. '
        'A company/title/sector match is an attribute, not connection evidence. Membership in our team does not itself create an edge. '
        'Use the named participants in deal_evidence for seller/advisor roles. Never infer those roles from job title or ordering. Use gender-neutral wording unless gender is explicitly recorded. '
        'If no exact attribute matches exist, say so without borrowing original demo facts. '
        'End with one short synthetic-data/as-of note. Avoid technical schema jargon.')
    spec['instructions']['sample_questions']=[{'question':q} for q in [
        'Who is the CEO of Willow Diagnostics?',
        'Show everyone directly connected to the CEO of Willow Diagnostics, with strengths and why.',
        'Show their contacts with strength at least 0.75, including people outside our team.',
        'Who can introduce us to the CFO of Cedarbridge Health?']]
    return spec
