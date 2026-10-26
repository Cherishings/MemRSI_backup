from pathlib import Path
p=Path("/root/.ssh/authorized_keys")
s=p.read_text();key=Path("/data/songziying/paos-libero-20261023/tunnel_authorized_key").read_text().strip();pub=key.split()[2]
lines=s.splitlines();matches=[i for i,v in enumerate(lines) if pub in v];assert len(matches)==1
lines[matches[0]]=key;p.write_text("\n".join(lines)+"\n");p.chmod(0o600)
