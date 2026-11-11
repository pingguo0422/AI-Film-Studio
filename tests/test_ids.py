from backend.app.db.ids import uuid7

def test_uuid7_has_version_and_variant_bits():
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"

def test_uuid7_is_time_ordered_for_sequential_calls():
    values = [uuid7() for _ in range(20)]
    assert values == sorted(values, key=lambda x: x.int)
