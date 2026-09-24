from pathlib import Path
import pytest
from home_readonly_mcp.policy import Policy
from home_readonly_mcp.service import HomeService

@pytest.fixture
def space(tmp_path, monkeypatch):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.setenv('USERPROFILE',str(home))
    monkeypatch.setenv('APPDATA',str(home/'AppData/Roaming'))
    monkeypatch.setenv('LOCALAPPDATA',str(home/'AppData/Local'))
    for name in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME'):
        monkeypatch.delenv(name,raising=False)
    root = home/'projects'
    root.mkdir()
    policy = Policy(root=root,mode='read_write')
    service = HomeService(policy)
    (root/'a.txt').write_text('hello\n世界\n',encoding='utf-8')
    return home,root,policy,service
