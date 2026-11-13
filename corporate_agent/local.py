"""Local session binding so query provenance observes the actual RAI connection."""
from pe_deal_graph.intro_rai import configuration
from relationalai.config import create_config

def local_configuration(timeout=12):
    base=configuration();session=base.get_session()
    cfg=create_config(snowflake_session=session)
    cfg.model.path=None;cfg.oplog.enabled=False;cfg.deployment=None
    cfg.execution.retries.enabled=False
    cfg.data.query_timeout_mins=timeout;cfg.data.poll_timeout_mins=timeout+1
    return cfg,session
