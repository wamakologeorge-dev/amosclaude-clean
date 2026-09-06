from amoscloud_ai.dns_control_plane import AmosclaudDNSJudge, DNSControlError, DNSRecord, DNSZone


def test_zone_upsert_and_action_judge_passes():
    zone = DNSZone("example.com")
    zone.upsert(DNSRecord("api.example.com", "A", "203.0.113.10", 300))
    result = AmosclaudDNSJudge().judge(zone)
    assert result.passed is True
    assert result.score == 100
    assert result.reasons == ()


def test_zone_rejects_out_of_zone_record():
    zone = DNSZone("example.com")
    try:
        zone.upsert(DNSRecord("api.other.com", "A", "203.0.113.10"))
    except DNSControlError:
        pass
    else:
        raise AssertionError("out-of-zone DNS record was accepted")


def test_judge_rejects_observed_state_that_does_not_match_desired_state():
    zone = DNSZone("example.com", [DNSRecord("api.example.com", "A", "203.0.113.10")])
    observed = [DNSRecord("api.example.com", "A", "203.0.113.11")]
    result = AmosclaudDNSJudge().judge(zone, observed_records=observed)
    assert result.passed is False
    assert "desired_state_observed" in result.reasons
