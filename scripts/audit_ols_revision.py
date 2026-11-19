#!/usr/bin/env python3
"""Read-only production inspection; mutation probe uses a temporary fixture only."""
import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    source=args.server.read_text()
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="asset_version")
    namespace={"Path":Path,"hashlib":hashlib,"json":json,"TYPE_DIR":{"model":"models"}}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(args.server),"exec"),namespace)
    with tempfile.TemporaryDirectory(prefix="ols-revision-proof-") as directory:
        root=Path(directory)
        item=root/"models/1/apple.json"
        item.parent.mkdir(parents=True)
        item.write_text('{"color":"red"}')
        row={"id":1,"name":"apple","category":"fruit"}
        stat=item.stat()
        before=namespace["asset_version"](root,"model",row)
        first=hashlib.sha256(item.read_bytes()).hexdigest()
        item.write_text('{"color":"tan"}')
        os.utime(item,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        after=namespace["asset_version"](root,"model",row)
        second=hashlib.sha256(item.read_bytes()).hexdigest()
        result={"server_source_sha256":hashlib.sha256(source.encode()).hexdigest(),
            "function":"asset_version","line":node.lineno,"probe":"temporary fixture; same size and mtime, different metadata bytes",
            "before_revision":before,"after_revision":after,"before_content_sha256":first,
            "after_content_sha256":second,"revision_unchanged":before==after,"content_changed":first!=second,
            "authoritative_content_revision":False,"required_policy":"strict full metadata validation",
            "production_assets_modified":False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result))


if __name__=="__main__":
    main()
