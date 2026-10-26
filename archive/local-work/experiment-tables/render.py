import importlib.util,sys
path='/home/edy/.codex/plugins/cache/openai-primary-runtime/documents/26.1022.11436/skills/documents/render_docx.py'
s=importlib.util.spec_from_file_location('renderer',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m._resolve_soffice=lambda:'/tmp/memrsi-doc-soffice'
sys.argv=[path,'outputs/paper-experiments/PAOS-experiment-tables.docx','--output_dir','work/experiment-tables/render','--emit_pdf']
original=m.convert_from_path
m.convert_from_path=lambda *a,**kw: original(*a,**dict(kw,poppler_path=str(__import__('pathlib').Path('work/experiment-tables/render-bin').resolve())))
m.main()
