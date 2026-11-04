"""Data export and hard deletion (explicit deletes so it also works on drivers without FK enforcement)."""
import json
from database.db import Session
from database.models import (User, ChildProfile, CaregiverQuestionnaire, Interaction, Favorite, InterestProfile, DailyActivity,
                             RecommendationLog, ConsentRecord, CaregiverSettings, Subscription, PaymentVerificationRequest,
                             AuditLog, ParentLink)


def delete_user(user_id):
    child = Session.query(ChildProfile).filter_by(caregiver_user_id=user_id).first()
    if child:
        for M in (Interaction, Favorite, InterestProfile, DailyActivity, RecommendationLog, CaregiverQuestionnaire, ParentLink):   # family links die with the child
            Session.query(M).filter_by(child_profile_id=child.id).delete()
        Session.delete(child)
    sub_ids = [s.id for s in Session.query(Subscription).filter_by(user_id=user_id).all()]
    if sub_ids:
        Session.query(PaymentVerificationRequest).filter(PaymentVerificationRequest.subscription_id.in_(sub_ids)).delete(synchronize_session=False)
    Session.query(Subscription).filter_by(user_id=user_id).delete()
    Session.query(ConsentRecord).filter_by(user_id=user_id).delete()
    Session.query(CaregiverSettings).filter_by(user_id=user_id).delete()
    Session.query(AuditLog).filter_by(administrator_id=user_id).update({"administrator_id": None})
    Session.query(User).filter_by(id=user_id).delete()
    Session.commit()


def export_user(user):
    def iso(v):
        return v.isoformat() if v else None
    child = Session.query(ChildProfile).filter_by(caregiver_user_id=user.id).first()
    data = {"username": user.username, "created_at": iso(user.created_at)}
    data["subscriptions"] = [{"plan": s.plan_code, "amount": s.amount, "currency": s.currency, "status": s.status,
                              "starts_at": iso(s.starts_at), "expires_at": iso(s.expires_at)}
                             for s in Session.query(Subscription).filter_by(user_id=user.id)]
    if child:
        q = Session.query(CaregiverQuestionnaire).filter_by(child_profile_id=child.id).first()
        data["child"] = {"display_name": child.display_name, "avatar": child.avatar, "age_years": child.age_years}
        data["questionnaire"] = json.loads(q.responses_json) if q else {}
        data["interests"] = [{"category": i.category, "score": i.interest_score, "evidence": i.evidence_count}
                             for i in Session.query(InterestProfile).filter_by(child_profile_id=child.id)]
        data["interactions"] = [{"type": i.interaction_type, "category": i.category, "content": i.content.title if i.content else None,
                                 "at": iso(i.occurred_at)} for i in Session.query(Interaction).filter_by(child_profile_id=child.id)]
        data["favorites"] = [{"title": f.content.title, "type": f.content.content_type, "url": f.content.canonical_url}
                             for f in Session.query(Favorite).filter_by(child_profile_id=child.id)]
        data["activities"] = [{"date": a.activity_date.isoformat(), "title": a.title, "notes": a.notes, "source": a.source}
                              for a in Session.query(DailyActivity).filter_by(child_profile_id=child.id)]
    return data