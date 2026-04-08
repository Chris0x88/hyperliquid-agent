from cli.daemon.iterators.catalyst_deleverage import CatalystDeleverageIterator, CatalystEvent


def test_add_external_catalysts_merges_and_dedupes():
    existing = [CatalystEvent(name="a", instrument="CL", event_date="2026-04-15")]
    it = CatalystDeleverageIterator(catalysts=existing)

    it.add_external_catalysts([
        CatalystEvent(name="b", instrument="CL", event_date="2026-04-16"),
        CatalystEvent(name="a", instrument="CL", event_date="2026-04-15"),  # duplicate
    ])

    names = [c.name for c in it._catalysts]
    assert "a" in names
    assert "b" in names
    assert len([n for n in names if n == "a"]) == 1  # not duplicated
