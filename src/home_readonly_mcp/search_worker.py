"""Trusted isolated regex worker: bounded input/output, no filesystem access requested."""
import json
import re
import sys


def main():
    request=json.loads(sys.stdin.buffer.read(52*1024*1024+1))
    pat=request['pattern']
    regex=re.compile(re.escape(pat) if request['fixed_strings'] else pat,
                     0 if request['case_sensitive'] else re.IGNORECASE)
    mode=request['output_mode'];limit=request['head_limit'];offset=request['offset'];context=request['context']
    results=[];seen=0;more=False;output_bytes=0
    for path,text in request['files']:
        lines=text.splitlines();hits=[]
        for n,line in enumerate(lines):
            if regex.search(line):
                hits.append(n)
        if mode=='files_with_matches':
            entries=[{'path':path}] if hits else []
        elif mode=='count':
            entries=[{'path':path,'count':len(hits)}] if hits else []
        else:
            entries=({'path':path,'line':i+1,'text':lines[i][:2000],
                      'context_before':[x[:1000] for x in lines[max(0,i-context):i]],
                      'context_after':[x[:1000] for x in lines[i+1:i+context+1]]} for i in hits)
        for row in entries:
            if seen>=offset:
                if len(results)>=limit:
                    more=True;break
                size=len(json.dumps(row,ensure_ascii=False).encode('utf-8'))
                if output_bytes+size>512*1024:
                    more=True;break
                results.append(row);output_bytes+=size
            seen+=1
        if more:break
    output={'results':results,'has_more':more,'next_offset':offset+len(results) if more else None}
    sys.stdout.buffer.write(json.dumps(output,ensure_ascii=False).encode('utf-8'))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        sys.stderr.write(type(exc).__name__+': '+str(exc)[:1000])
        raise SystemExit(2)
