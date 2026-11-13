"""Resume the configured engine only; never silently create/switch a backend."""
from unittest.mock import Mock,patch
import pytest
from corporate_agent.runtime import ready_engine,ENGINE


def test_resume_suspended_engine_and_wait_for_ready():
    session=Mock()
    states=[[{'status':'SUSPENDED'}],[{'status':'PENDING'}],[{'status':'PROVISIONING'}],[{'status':'READY'}]]
    with patch('corporate_agent.runtime.rows',side_effect=states),patch('corporate_agent.runtime.time.sleep'):
        assert ready_engine(session)==[{'status':'READY'}]
    session.sql.assert_called_once_with('CALL RELATIONALAI.API.RESUME_REASONER_ASYNC(?,?)',params=['LOGIC',ENGINE])


def test_unhealthy_engine_is_not_replaced():
    session=Mock()
    with patch('corporate_agent.runtime.rows',return_value=[{'status':'FAILED'}]):
        with pytest.raises(RuntimeError,match='no fallback'):ready_engine(session)
    session.sql.assert_not_called()


def test_resume_has_bounded_wait():
    session=Mock()
    with patch('corporate_agent.runtime.rows',return_value=[{'status':'PROVISIONING'}]),patch('corporate_agent.runtime.time.monotonic',side_effect=[0,121]):
        with pytest.raises(RuntimeError,match='no fallback'):ready_engine(session)
    session.sql.assert_not_called()
