"""Regression test for plot_hive_mapper on a populated HiveMapper.

Guards against the AttributeError bug where plot_hive_mapper read
info.rtt_ms, a field NodeInfo never had (the real equivalent is the
latency_ms property). This was masked for a long time because a
ping_id-vs-flood_id bug upstream meant discovery floods never actually
populated a HiveMapper, so plot_hive_mapper only ever ran on empty
mappers in practice.
"""

from hivemind_bus_client.hive_map import HiveMapper, NodeInfo

from hivescope.topology_plot import plot_hive_mapper


def test_plot_hive_mapper_renders_populated_hive(tmp_path):
    mapper = HiveMapper()

    mapper.nodes["root"] = NodeInfo(
        peer="root",
        site_id="site-a",
        timestamp=1000.0,
        received_at=1000.0,
        lang="en-us",
        trusted=True,
    )
    mapper.nodes["satellite-1"] = NodeInfo(
        peer="satellite-1",
        site_id="site-a",
        timestamp=1000.0,
        received_at=1000.05,
        lang="en-us",
        trusted=False,
    )
    mapper.nodes["satellite-2"] = NodeInfo(
        peer="satellite-2",
        site_id=None,
        timestamp=None,
        received_at=None,
    )

    mapper.edges["root"] = {"satellite-1", "satellite-2"}

    out_path = tmp_path / "hive_map.png"

    result = plot_hive_mapper(mapper, str(out_path), root_peer="root")

    assert result == str(out_path.resolve()) or result == str(out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
