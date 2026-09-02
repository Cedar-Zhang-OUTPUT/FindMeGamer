import FindMeGamerAPI
import Foundation
import Testing

@testable import FindMeGamerCore

@Suite struct DomainMappingTests {
  @Test func mapsGameAndCreatorProfilesWithRecursiveJSONAndContactSemantics() throws {
    let gameCard = try DomainMapper.gameCard(
      decode(
        Components.Schemas.GameProfileCard.self,
        [
          "type": "game",
          "id": "10000000-0000-4000-8000-000000000001",
          "name": "Signal Garden",
          "steam_app_id": "730",
          "canonical_url": "https://store.steampowered.com/app/730",
          "favorite": true,
          "current_facts": [
            "players": 12,
            "ratio": 1.5,
            "released": true,
            "nullable": NSNull(),
            "nested": ["tags": ["co-op", "strategy"]],
          ],
          "brief": ["hook": "Build together"],
          "source_status": ["steam": "available"],
          "last_analyzed_at": NSNull(),
          "next_analysis_at": "2026-09-04T00:00:00Z",
        ]
      )
    )
    #expect(gameCard.id == UUID(uuidString: "10000000-0000-4000-8000-000000000001"))
    #expect(gameCard.steamAppID == "730")
    #expect(gameCard.lastAnalyzedAt == nil)
    #expect(gameCard.nextAnalysisAt != nil)
    #expect(
      gameCard.currentFacts["nested"]
        == .object(["tags": .array([.string("co-op"), .string("strategy")])])
    )
    #expect(gameCard.currentFacts["nullable"] == .null)

    let manual = try DomainMapper.creatorCard(
      decode(
        Components.Schemas.CreatorProfileCard.self,
        creatorCardJSON(contact: [
          "email": "manual@example.com",
          "source": "manual",
          "source_url": NSNull(),
          "validation_state": "valid",
        ])
      )
    )
    let discovered = try DomainMapper.creatorCard(
      decode(
        Components.Schemas.CreatorProfileCard.self,
        creatorCardJSON(contact: [
          "email": "public@example.com",
          "source": "channel_about",
          "source_url": "https://youtube.com/@signal/about",
          "validation_state": "unverified",
        ])
      )
    )
    let unavailable = try DomainMapper.creatorCard(
      decode(
        Components.Schemas.CreatorProfileCard.self,
        creatorCardJSON(contact: NSNull())
      )
    )
    #expect(manual.contact?.availability == .manual)
    #expect(discovered.contact?.availability == .discovered)
    #expect(unavailable.contact == nil)
    #expect(unavailable.contactAvailability == .unavailable)

    let creator = try DomainMapper.creatorProfile(
      decode(
        Components.Schemas.CreatorProfileDetail.self,
        creatorDetailJSON()
      )
    )
    #expect(creator.manualNotes == "Met at PAX")
    #expect(creator.analysis["audience"] == .object(["region": .string("US")]))
    #expect(creator.modelMetadata["model"] == .string("deepseek-v4-pro"))
    #expect(creator.promptMetadata["version"] == .integer(3))
  }

  @Test func mapsAnalysisSubmissionsAndChangedJobsIncludingNullableState() throws {
    let job = try DomainMapper.analysisJob(
      decode(Components.Schemas.AnalysisJobResponse.self, analysisJobJSON())
    )
    #expect(job.id == UUID(uuidString: "20000000-0000-4000-8000-000000000001"))
    #expect(job.profileType == .creator)
    #expect(job.mode == .reanalyze)
    #expect(job.status == .failed)
    #expect(job.stage == .analyzing)
    #expect(job.failure?.code == "provider_timeout")
    #expect(job.completedAt != nil)

    let existing = try DomainMapper.existingProfile(
      decode(
        Components.Schemas.ExistingProfileResponse.self,
        [
          "outcome": "existing_profile",
          "existing_profile_id": "20000000-0000-4000-8000-000000000002",
          "target_type": "game",
          "canonical_target_id": "730",
          "canonical_url": "https://store.steampowered.com/app/730",
        ]
      )
    )
    #expect(existing.profileID == UUID(uuidString: "20000000-0000-4000-8000-000000000002"))
    #expect(existing.profileType == .game)

    let page = try DomainMapper.jobChangePage(
      decode(
        Components.Schemas.ChangedJobsResponse.self,
        [
          "items": [
            changedAnalysisJobJSON(),
            changedMatchJobJSON(),
          ],
          "cursor": "opaque:next",
          "has_more": true,
          "affected_profile_ids": [
            "20000000-0000-4000-8000-000000000002"
          ],
        ]
      )
    )
    #expect(page.cursor == "opaque:next")
    #expect(page.hasMore)
    #expect(page.items.count == 2)
    guard case .analysis(let changedAnalysis) = page.items[0] else {
      Issue.record("Expected analysis job change")
      return
    }
    guard case .match(let changedMatch) = page.items[1] else {
      Issue.record("Expected Match job change")
      return
    }
    #expect(changedAnalysis.stage == nil)
    #expect(changedMatch.stage == .pairwise)
    #expect(changedMatch.supersedesID == nil)
  }

  @Test func mapsMatchDetailWithoutScoresAndPreservesBackendArrayOrder() throws {
    let result = try DomainMapper.matchResult(
      decode(Components.Schemas.MatchDetail.self, matchDetailJSON())
    )
    #expect(result.state == .available)
    #expect(result.recommendedMatches.map(\.creator.name) == ["Second", "First"])
    #expect(result.otherMatches.map(\.creator.name) == ["Other"])
    #expect(result.recommendedMatches[0].label == .strong)
    #expect(result.recommendedMatches[0].group == .recommended)
    #expect(result.recommendedMatches[0].outreach.sendState == .sent)
    #expect(result.recommendedMatches[0].outreach.responseState == .accepted)
    #expect(result.recommendedMatches[0].brief.brandSafety.analysis == "Suitable")
    #expect(result.recommendedMatches[0].dimensionOutcomes.performanceFit == "Good")

    let candidateReflection = String(reflecting: result.recommendedMatches[0]).lowercased()
    for forbidden in ["totalscore", "dimensionscores", "backendorder", " rank", " score"] {
      #expect(!candidateReflection.contains(forbidden))
    }
  }

  @Test func mapsOutreachAndSettingsWithoutResponseSecrets() throws {
    let campaign = try DomainMapper.campaign(
      decode(Components.Schemas.OutreachCampaignDetail.self, campaignDetailJSON())
    )
    #expect(campaign.state == .completed)
    #expect(campaign.metrics.sentCreators == 2)
    #expect(campaign.sendBatches[0].deliveries[0].sendState == .sent)

    let template = try DomainMapper.template(
      decode(Components.Schemas.OutreachTemplateResponse.self, templateJSON())
    )
    let preview = try DomainMapper.renderedEmail(
      decode(
        Components.Schemas.RenderedDelivery.self,
        ["subject": "Hello", "markdown": "Body", "html": "<p>Body</p>"]
      )
    )
    let smtp = try DomainMapper.smtpSettings(
      decode(Components.Schemas.SMTPSettingsResponse.self, smtpJSON())
    )
    let connection = try DomainMapper.connectionStatus(
      decode(
        Components.Schemas.ConnectionStatusResponse.self,
        [
          "configured": true,
          "last_test_status": "success",
          "last_tested_at": "2026-09-03T00:00:00Z",
        ]
      ),
      service: .deepSeek
    )
    #expect(template.isDefault)
    #expect(preview.html == "<p>Body</p>")
    #expect(smtp.encryption == .startTLS)
    #expect(connection.service == .deepSeek)
    #expect(connection.lastTestStatus == .success)

    let combined = [
      String(reflecting: campaign),
      String(reflecting: template),
      String(reflecting: smtp),
      String(reflecting: connection),
    ].joined(separator: " ")
    for secret in ["WORKSPACE-CANARY", "SMTP-PASSWORD-CANARY", "CONNECTION-SECRET-CANARY"] {
      #expect(!combined.contains(secret))
    }
  }

  @Test func invalidGeneratedUUIDFailsAsSafeAPIError() throws {
    let generated = try decode(
      Components.Schemas.GameProfileCard.self,
      [
        "type": "game",
        "id": "not-a-uuid",
        "name": "Broken",
        "steam_app_id": "1",
        "canonical_url": "https://example.com/game",
        "favorite": false,
        "current_facts": [:],
        "brief": [:],
        "source_status": [:],
        "last_analyzed_at": NSNull(),
        "next_analysis_at": NSNull(),
      ]
    )

    do {
      _ = try DomainMapper.gameCard(generated)
      Issue.record("Expected safe invalid-response failure")
    } catch let error as APIError {
      #expect(error.code == "invalid_response")
      #expect(!error.retryable)
      #expect(!String(describing: error).contains("not-a-uuid"))
    }
  }
}

private func decode<T: Decodable>(_ type: T.Type, _ object: Any) throws -> T {
  let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
  let decoder = JSONDecoder()
  decoder.dateDecodingStrategy = .iso8601
  return try decoder.decode(type, from: data)
}

private func creatorCardJSON(contact: Any) -> [String: Any] {
  [
    "type": "creator",
    "id": "10000000-0000-4000-8000-000000000002",
    "name": "Signal Channel",
    "youtube_channel_id": "UC-signal",
    "canonical_url": "https://youtube.com/@signal",
    "favorite": false,
    "current_facts": ["subscribers": 2_000],
    "brief": ["focus": "strategy"],
    "source_status": ["youtube": "available"],
    "last_analyzed_at": "2026-09-03T00:00:00Z",
    "next_analysis_at": NSNull(),
    "contact": contact,
  ]
}

private func creatorDetailJSON() -> [String: Any] {
  var value = creatorCardJSON(contact: [
    "email": "manual@example.com",
    "source": "manual",
    "source_url": NSNull(),
    "validation_state": "valid",
  ])
  value["analysis"] = ["audience": ["region": "US"]]
  value["model_metadata"] = ["model": "deepseek-v4-pro"]
  value["prompt_metadata"] = ["version": 3]
  value["manual_notes"] = "Met at PAX"
  return value
}

private func analysisJobJSON() -> [String: Any] {
  [
    "outcome": "job",
    "id": "20000000-0000-4000-8000-000000000001",
    "target_type": "creator",
    "canonical_target_id": "UC-signal",
    "canonical_url": "https://youtube.com/@signal",
    "mode": "reanalyze",
    "status": "failed",
    "stage": "analyzing",
    "completed_units": 2,
    "total_units": 4,
    "retryable": true,
    "correlation_id": "correlation-1",
    "profile_id": NSNull(),
    "created_at": "2026-09-03T00:00:00Z",
    "updated_at": "2026-09-03T00:02:00Z",
    "started_at": "2026-09-03T00:01:00Z",
    "completed_at": "2026-09-03T00:02:00Z",
    "error": [
      "code": "provider_timeout",
      "message": "Analysis is temporarily unavailable. Please retry.",
    ],
  ]
}

private func changedAnalysisJobJSON() -> [String: Any] {
  var value = analysisJobJSON()
  value["kind"] = "analysis"
  value["resource_id"] = "20000000-0000-4000-8000-000000000001"
  value["status"] = "running"
  value["stage"] = NSNull()
  value["completed_at"] = NSNull()
  value["error"] = NSNull()
  return value
}

private func changedMatchJobJSON() -> [String: Any] {
  [
    "kind": "match",
    "resource_id": "30000000-0000-4000-8000-000000000001",
    "status": "running",
    "stage": "pairwise",
    "completed_units": 2,
    "total_units": 5,
    "result_count": 0,
    "retryable": false,
    "error": NSNull(),
    "correlation_id": NSNull(),
    "game_id": "30000000-0000-4000-8000-000000000002",
    "supersedes_id": NSNull(),
    "created_at": "2026-09-03T00:00:00Z",
    "updated_at": "2026-09-03T00:01:00Z",
    "started_at": "2026-09-03T00:00:01Z",
    "completed_at": NSNull(),
  ]
}

private func matchDetailJSON() -> [String: Any] {
  [
    "id": "30000000-0000-4000-8000-000000000001",
    "game": matchGameJSON(),
    "status": "succeeded",
    "stage": "ranking",
    "completed_units": 5,
    "total_units": 5,
    "result_count": 3,
    "retryable": false,
    "error": NSNull(),
    "correlation_id": "match-correlation",
    "supersedes_id": NSNull(),
    "created_at": "2026-09-03T00:00:00Z",
    "updated_at": "2026-09-03T00:05:00Z",
    "started_at": "2026-09-03T00:00:01Z",
    "completed_at": "2026-09-03T00:05:00Z",
    "result_state": "available",
    "recommended_matches": [
      matchItemJSON(name: "Second", suffix: "2", label: "Strong Match", group: "recommended"),
      matchItemJSON(name: "First", suffix: "1", label: "Good Match", group: "recommended"),
    ],
    "other_matches": [
      matchItemJSON(name: "Other", suffix: "3", label: "Limited Match", group: "other")
    ],
  ]
}

private func matchGameJSON() -> [String: Any] {
  [
    "id": "30000000-0000-4000-8000-000000000002",
    "name": "Signal Garden",
    "steam_app_id": "730",
    "canonical_url": "https://store.steampowered.com/app/730",
    "cover_url": NSNull(),
  ]
}

private func matchItemJSON(name: String, suffix: String, label: String, group: String)
  -> [String: Any]
{
  let dimension: [String: Any] = ["analysis": "Suitable", "evidence": ["Public evidence"]]
  return [
    "creator": [
      "id": "40000000-0000-4000-8000-00000000000\(suffix)",
      "name": name,
      "youtube_channel_id": "UC-\(suffix)",
      "canonical_url": "https://youtube.com/@creator\(suffix)",
      "favorite": suffix == "1",
      "contact_available": true,
      "contact": [
        "email": "creator\(suffix)@example.com",
        "source": "manual",
        "source_url": NSNull(),
        "validation_state": "valid",
      ],
      "avatar_url": NSNull(),
      "performance_summary": "Steady views",
      "subscriber_count": 10_000,
      "recent_average_views": 2_000,
      "recent_median_views": 1_800,
    ],
    "result_group": group,
    "qualitative_label": label,
    "dimension_outcomes": [
      "content_fit": "Strong",
      "audience_fit": "Strong",
      "performance_fit": "Good",
      "promotion_fit": "Strong",
      "brand_safety": "Suitable",
    ],
    "match_reasons": ["Audience overlap"],
    "match_brief": [
      "content_fit": dimension,
      "audience_fit": dimension,
      "performance_fit": dimension,
      "promotion_fit": dimension,
      "brand_safety": dimension,
      "strengths": ["Audience overlap"],
      "risks": ["Schedule"],
      "evidence": ["Public evidence"],
      "match_reasons": ["Audience overlap"],
    ],
    "outreach": [
      "delivery_id": "50000000-0000-4000-8000-00000000000\(suffix)",
      "send_state": "sent",
      "response_state": "accepted",
    ],
  ]
}

private func campaignDetailJSON() -> [String: Any] {
  [
    "id": "60000000-0000-4000-8000-000000000001",
    "match_task_id": "30000000-0000-4000-8000-000000000001",
    "game": campaignGameJSON(),
    "state": "completed",
    "send_batch_count": 1,
    "metrics": campaignMetricsJSON(),
    "created_at": "2026-09-03T00:00:00Z",
    "latest_activity_at": "2026-09-03T00:06:00Z",
    "send_batches": [sendBatchDetailJSON()],
  ]
}

private func campaignGameJSON() -> [String: Any] {
  [
    "id": "30000000-0000-4000-8000-000000000002",
    "name": "Signal Garden",
    "steam_app_id": "730",
    "steam_url": "https://store.steampowered.com/app/730",
    "cover_url": NSNull(),
  ]
}

private func campaignMetricsJSON() -> [String: Any] {
  [
    "sent_creators": 2,
    "accepted": 1,
    "declined": 0,
    "no_response": 1,
    "failed": 0,
    "response_rate": 0.5,
  ]
}

private func sendBatchDetailJSON() -> [String: Any] {
  [
    "id": "70000000-0000-4000-8000-000000000001",
    "campaign_id": "60000000-0000-4000-8000-000000000001",
    "template_id": "80000000-0000-4000-8000-000000000001",
    "template_name": "Launch",
    "template_version": 2,
    "requested_creator_ids": ["40000000-0000-4000-8000-000000000001"],
    "requested_at": "2026-09-03T00:03:00Z",
    "state": "sent",
    "deliveries": [
      [
        "accepted_label": "Yes",
        "campaign_id": "60000000-0000-4000-8000-000000000001",
        "can_resend": true,
        "created_at": "2026-09-03T00:03:00Z",
        "creator": [
          "id": "40000000-0000-4000-8000-000000000001",
          "name": "First",
          "youtube_channel_id": "UC-1",
          "canonical_url": "https://youtube.com/@creator1",
          "avatar_url": NSNull(),
        ],
        "declined_label": "No",
        "failed_at": NSNull(),
        "id": "50000000-0000-4000-8000-000000000001",
        "is_current": true,
        "recipient_email": "creator1@example.com",
        "rendered_html": "<p>Hello</p>",
        "rendered_markdown": "Hello",
        "rendered_subject": "Hello",
        "reply_to": "reply@example.com",
        "send_state": "sent",
        "response_state": "accepted",
        "resends_delivery_id": NSNull(),
        "responded_at": "2026-09-03T00:06:00Z",
        "send_batch_id": "70000000-0000-4000-8000-000000000001",
        "sender_address": "sender@example.com",
        "sender_name": "Sender",
        "sending_at": "2026-09-03T00:04:00Z",
        "sent_at": "2026-09-03T00:05:00Z",
        "smtp_error": NSNull(),
        "superseded_at": NSNull(),
        "superseded_by_delivery_id": NSNull(),
        "template_name": "Launch",
        "template_version": 2,
      ]
    ],
  ]
}

private func templateJSON() -> [String: Any] {
  [
    "id": "80000000-0000-4000-8000-000000000001",
    "name": "Launch",
    "version": 2,
    "subject_template": "Hello {{creator_name}}",
    "body_markdown": "Play {{game_name}}",
    "accepted_label": "Yes",
    "declined_label": "No",
    "is_default": true,
    "created_at": "2026-09-03T00:00:00Z",
    "updated_at": "2026-09-03T00:01:00Z",
  ]
}

private func smtpJSON() -> [String: Any] {
  [
    "configured": true,
    "host": "smtp.example.com",
    "port": 587,
    "encryption": "starttls",
    "username": "mailer@example.com",
    "from_name": "Find Me Gamer",
    "reply_to": "reply@example.com",
    "emails_per_minute": 10,
    "last_test_status": "success",
    "last_tested_at": "2026-09-03T00:00:00Z",
  ]
}
