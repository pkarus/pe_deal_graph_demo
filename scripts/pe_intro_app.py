"""Clean RAI app ontology over the existing enriched 1M PE test.

This is a semantic model of existing data, not another graph calculation. The
SDK initializes Person, Organization and TeamMember tables; other outputs are
views over the existing test attributes, connections and evidence. No lab sources, engine
changes, graph refresh, or Cortex changes. On-demand route procedures remain in
CONNECTED_1M_INTRO_TEST and are not represented as precomputed paths here.
"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pe_deal_graph import settings

SOURCE = settings.schema('CONNECTED_1M_INTRO_TEST')
TARGET = settings.schema('INTRO_APP')


def build_model():
    from relationalai.config import create_config, DeploymentConfig
    from relationalai.semantics import Model, String, Float, Date
    os.environ['RAI_CONFIG_FILE_PATH'] = str(ROOT / 'raiconfig.yaml')
    cfg = create_config()
    cfg.model.path = None
    cfg.oplog.enabled = True
    cfg.oplog.backend = 'snowflake'
    cfg.execution.retries.enabled = False
    conn = cfg.get_default_connection()
    conn.role = settings.ADMIN_ROLE
    conn.warehouse = settings.WAREHOUSE
    cfg.deployment = DeploymentConfig(
        schema=TARGET, meta_schema=TARGET + '_META', role=settings.ADMIN_ROLE,
        auto_deploy=False,
        schedules={'manual': {'interval_s': 0, 'run_on_deploy': False}},
        outputs={'type': 'view', 'reasoner': 'sql', 'schedule': 'manual'})
    m = Model('PE Introductions — Enriched 1M Test', config=cfg)
    person = m.Concept('Person', identify_by={'id': String})
    person.name = m.Property(f'{person} has {String:name}')
    organization = m.Concept('Organization', identify_by={'id': String})
    organization.name = m.Property(f'{organization} has {String:name}')
    # The combined attribute view has no role ID. Its natural job identity is
    # person + organization + title + start date; end date is optional metadata.
    role = m.Concept('Employment', identify_by={
        'person': person, 'organization': organization, 'title': String, 'start_date': Date})
    role.end_date = m.Property(f'{role} ends on {Date:end_date}')
    role.role_type = m.Property(f'{role} has {String:role_type}')
    team = m.Concept('TeamMember', extends=[person])
    team.team_name = m.Property(f'{team} belongs to {String:team_name}')
    team.join_date = m.Property(f'{team} joined on {Date:join_date}')
    connection = m.Concept('Connection', identify_by={'person_a': person, 'person_b': person})
    connection.strength = m.Property(f'{connection} has modeled {Float:strength}')
    connection.evidence = m.Property(f'{connection} is supported by {String:evidence}')
    interaction = m.Concept('Interaction', identify_by={'id': String})
    interaction.team_person = m.Property(f'{interaction} involves team member {person:team_person}')
    interaction.contact = m.Property(f'{interaction} involves contact {person:contact}')
    interaction.date = m.Property(f'{interaction} happened on {Date:date}')
    interaction.sentiment = m.Property(f'{interaction} has {String:sentiment}')
    deal = m.Concept('Deal', identify_by={'id': String})
    deal.close_date = m.Property(f'{deal} closed on {Date:close_date}')
    deal.structure = m.Property(f'{deal} has {String:structure}')
    deal.target = m.Property(f'{deal} concerns {organization:target}')
    party = m.Concept('DealParticipation', identify_by={'deal': deal, 'person': person, 'party_role': String})

    p = m.Table(SOURCE + '.PERSON')
    m.define(person.new(id=p.ID))
    m.define(person.lookup(id=p.ID).name(p.NAME))
    a = m.Table(SOURCE + '.PERSON_ATTRIBUTES')
    m.define(organization.new(id=a.ORG_ID))
    m.define(organization.lookup(id=a.ORG_ID).name(a.ORGANIZATION))
    job = role.new(person=person.lookup(id=a.PERSON_ID), organization=organization.lookup(id=a.ORG_ID),
                   title=a.TITLE, start_date=a.START_DATE)
    m.define(job)
    m.define(job.end_date(a.END_DATE))
    m.define(job.role_type(a.ROLE_TYPE))
    t = m.Table(SOURCE + '.TEAM_MEMBERS')
    member = person.lookup(id=t.PERSON_ID)
    m.define(team(member))
    m.define(team.lookup(id=t.PERSON_ID).team_name(t.TEAM_NAME))
    m.define(team.lookup(id=t.PERSON_ID).join_date(t.JOIN_DATE))
    e = m.Table(SOURCE + '.KNOWS_EDGES')
    edge = connection.new(person_a=person.lookup(id=e.SRC), person_b=person.lookup(id=e.DST))
    m.where(e.SRC < e.DST).define(edge)
    m.where(e.SRC < e.DST).define(edge.strength(e.STRENGTH))
    m.where(e.SRC < e.DST).define(edge.evidence(e.EVIDENCE))
    i = m.Table(SOURCE + '.CRM_INTERACTION')
    event = interaction.new(id=i.INTERACTION_ID)
    m.define(event)
    m.define(event.team_person(person.lookup(id=i.OUR_PERSON_ID)))
    m.define(event.contact(person.lookup(id=i.COUNTERPARTY_PERSON_ID)))
    m.define(event.date(i.INTERACTION_DATE))
    m.define(event.sentiment(i.SENTIMENT))
    d = m.Table(SOURCE + '.DEAL_PARTY')
    transaction = deal.new(id=d.TRANSACTION_ID)
    m.define(transaction)
    m.define(transaction.close_date(d.CLOSE_DATE))
    m.define(transaction.structure(d.STRUCTURE))
    m.define(transaction.target(organization.lookup(id=d.TARGET_ID)))
    m.define(party.new(deal=deal.lookup(id=d.TRANSACTION_ID),
                       person=person.lookup(id=d.LEAD_PERSON_ID), party_role=d.PARTY_ROLE))
    return m


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy', action='store_true')
    args = parser.parse_args()
    model = build_model()
    if args.deploy:
        # Model.deploy records the supported oplog and creates only this dedicated
        # schema/meta pair. Three structural tables need one manual SQL refresh;
        # connection outputs remain views and no graph algorithms run.
        workdir = ROOT / "build" / "pe_intro_app"
        workdir.mkdir(parents=True, exist_ok=True)
        os.chdir(workdir)
        model.deploy()
    else:
        from relationalai.semantics.backends.multi_reasoner_executor import MultiReasonerExecutor
        executor = MultiReasonerExecutor(model.config)
        _, plan = executor._create_model_plan(model.to_metamodel())
        assert all(b.reasoner_type == 'sql' for b in plan.blocks)
        print('Target:', TARGET)
        print('Concepts:', ', '.join(c._name for c in model.concepts))
        print('Plan:', len(plan.blocks), 'SQL blocks; no Logic reasoner')
