import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "RUCKUS"))


@pytest.fixture
def tmp_instance(tmp_path):
    """Isolated instance dir for tests touching disk (certs, secrets, profiles)."""
    inst = tmp_path / "instance"
    inst.mkdir()
    return str(inst)
