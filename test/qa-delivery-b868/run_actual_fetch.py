import importlib.util,json,sys,urllib.request
from pathlib import Path
base=Path(__file__).resolve().parents[2]/'inputs/delivery-b868';info=json.loads((base/'raw/fetch-package-inputs.json').read_bytes());root=Path(info[sys.argv[1]]['root']);module_path=root/'fetch_source.py';spec=importlib.util.spec_from_file_location('actual_fetch',module_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=urllib.request.urlopen;archive=base/'raw'/('source-network-'+sys.argv[1]+'.zip')
class Capture:
 def __init__(self,response):self.response=response;self.file=archive.open('wb')
 def read(self,*a):b=self.response.read(*a);self.file.write(b);return b
 def __enter__(self):return self
 def __exit__(self,*a):self.file.close();self.response.close()
def opener(*a,**kw):return Capture(original(*a,**kw))
m.urllib.request.urlopen=opener
try:result=m.fetch(root)
except Exception as e:
 (base/'raw'/('fetch-'+sys.argv[1]+'-failure.json')).write_text(json.dumps({'type':type(e).__name__,'reason':str(e),'source_published':(root/'source').exists()},indent=2),encoding='utf-8');raise
(base/'raw'/('fetch-'+sys.argv[1]+'-result.json')).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
