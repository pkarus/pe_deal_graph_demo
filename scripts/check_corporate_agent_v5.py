"""Exercise the deployed agent as its published role, then verify the answers."""
import argparse,json
from pathlib import Path
from corporate_agent.deploy import chat
from corporate_agent.acceptance import main as acceptance

parser=argparse.ArgumentParser();parser.add_argument('--ceo-top-n',type=int,choices=[5,10],default=5)
args=parser.parse_args()
QUESTIONS={
    'ceo':f'Who can introduce us to Soren T. Bellamy, the CEO of Aspenview Materials? Show the top {args.ceo_top_n} connections.',
    'pair':'How are Anika B. Bergstrom (PE_P0001) and Soren T. Bellamy (CORP_P000000373) related, and can Anika introduce us to Soren? Only show routes with normalized strength at least 0.1.',
    'head':'Who on our team is connected to the head of data of Aspenview Materials? Show the top five connections with their evidence.',
    'missing':'Who can introduce us to the CEO of Nonexistent Polar Widget Company 999999?',
}
for name,question in QUESTIONS.items():
    print('START',name,flush=True)
    path=Path(f'artifacts/corporate_agent_chat_{name}.json')
    chat(question,str(path),role='RAI_USER')
    doc=json.loads(path.read_text())
    if name!='missing':
        results=[b['tool_result'] for b in doc['response']['content']
                 if b['type']=='tool_result' and b['tool_result']['name']=='execute_pyrel']
        assert len(results)==1,(name,'expected one successful attempt')
        result=json.loads(results[0]['content'][0]['json']['result'])
        assert result['status']=='OK',result
        assert result['transaction_ids'] and result['total_connections']>=len(result['rows'])
    print('DONE',name,flush=True)
acceptance()
