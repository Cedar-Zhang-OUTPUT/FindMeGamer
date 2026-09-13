"""Small shared Creator Library with explicit evidence and identity boundaries."""

import re
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import APIError
from app.core.idempotency import utc_now
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import (
    CreatorProfile,
    CreatorContact,
    CreatorWork,
    GameProfile,
)
from app.schemas.creator_library import (
    CreatorCreate,
    CreatorFields,
    CreatorPatch,
    CreatorDetail,
    CreatorIdentity,
    CreatorPage,
    ContactCreate,
    ContactPatch,
    ContactDetail,
    ContactFields,
    IdentityUpdate,
    WorkCreate,
    WorkPatch,
    WorkFields,
    WorkDetail,
    WorkPage,
)


def error(status, code, message):
    return APIError(status_code=status, code=code, message=message)


def safe_fields(schema, values):
    result = {}
    for key, value in values.items():
        if key not in schema.model_fields:
            continue
        try:
            result[key] = schema.model_validate({key: value}).model_dump(mode="json")[
                key
            ]
        except ValidationError:
            pass
    return schema.model_validate(result)


def source_fields(creator):
    from app.core.content_languages import creator_source_languages

    facts = creator.current_facts or {}
    return safe_fields(
        CreatorFields,
        {
            "name": facts.get("title") or facts.get("channel_name"),
            "public_name": facts.get("title") or facts.get("channel_name"),
            "source_notes": (
                "Public addressing uses the published channel name, not an inferred personal name."
                if facts.get("title") or facts.get("channel_name")
                else None
            ),
            "handle": facts.get("custom_url"),
            "profile_url": creator.canonical_url or None,
            "avatar_url": facts.get("avatar_url"),
            "description": facts.get("description"),
            "follower_count": facts.get("subscriber_count"),
            "follower_count_collected_at": facts.get("follower_count_collected_at")
            or creator.last_analyzed_at,
            "languages": creator_source_languages(creator),
            "country_code": facts.get("country"),
        },
    )


def effective_fields(creator):
    manual = dict(creator.manual_overrides or {})
    if "internal_notes" not in manual and creator.manual_notes is not None:
        manual["internal_notes"] = creator.manual_notes
    return CreatorFields.model_validate(
        source_fields(creator).model_dump(mode="json") | manual
    )


def contact_detail(contact, creator):
    return ContactDetail(
        id=contact.id,
        email=contact.email,
        purpose=contact.purpose,
        source_url=contact.source_url,
        is_active=contact.is_active,
        verification_notes=(contact.manual_overrides or {}).get("verification_notes"),
        origin="manual" if contact.is_manual else "source",
        source_type=contact.source_type,
        validation_state=contact.validation_state,
        source_fields=contact.source_fields or {},
        manual_overrides=contact.manual_overrides or {},
        identity_revision=contact.identity_revision,
        is_current_identity=contact.identity_revision == creator.identity_revision,
        updated_at=contact.updated_at,
    )


def detail(creator):
    from app.repositories.library_queries import creator_summary

    return CreatorDetail(
        **effective_fields(creator).model_dump(),
        id=creator.id,
        platform=creator.platform,
        revision=creator.manual_revision,
        favorite=creator.favorite,
        source_identity=CreatorIdentity(
            platform=creator.platform,
            account_id=creator.platform_account_id or creator.youtube_channel_id,
            canonical_url=creator.canonical_url or None,
            revision=creator.identity_revision,
        ),
        source_fields=source_fields(creator),
        manual_overrides=creator.manual_overrides or {},
        overridden_fields=sorted(creator.manual_overrides or {}),
        contacts=[
            contact_detail(c, creator)
            for c in sorted(creator.contacts, key=lambda c: (c.created_at, str(c.id)))
        ],
        work_count=sum(
            w.identity_revision == creator.identity_revision for w in creator.works
        ),
        last_analyzed_at=creator.last_analyzed_at,
        next_analysis_at=creator.next_analysis_at,
        analysis_available=(
            creator.platform == "youtube" and creator.youtube_channel_id is not None
        )
        or (creator.platform == "x" and creator.platform_account_id is not None),
        analysis=creator.analysis or {},
        brief=creator.brief or {},
        source_status=creator.source_status or {},
        **creator_summary(creator),
    )


def work_detail(work, creator):
    values = safe_fields(WorkFields, work.source_fields or {}).model_dump(
        mode="json"
    ) | (work.manual_overrides or {})
    effective = WorkFields.model_validate(values)
    return WorkDetail(
        **effective.model_dump(exclude={"platform"}),
        id=work.id,
        creator_id=work.creator_id,
        platform=effective.platform or work.platform,
        source_platform=work.platform,
        origin=work.origin,
        revision=work.revision,
        identity_revision=work.identity_revision,
        is_current_identity=work.identity_revision == creator.identity_revision,
        source_content_id=work.source_content_id,
        source_collected_at=work.source_collected_at,
        source_fields=work.source_fields or {},
        manual_overrides=work.manual_overrides or {},
    )


def normalized_identity(platform, account_id, profile_url):
    account_id = account_id.strip() if account_id else None
    if not account_id and not profile_url:
        raise error(422, "request_invalid", "A profile URL or account ID is required.")
    if account_id:
        pattern = {
            "youtube": r"UC[A-Za-z0-9_-]{3,126}",
            "x": r"[1-9][0-9]{0,31}",
            "twitch": r"[1-9][0-9]{0,31}",
            "instagram": r"[A-Za-z0-9._]{1,128}",
        }[platform]
        if not re.fullmatch(pattern, account_id):
            raise error(422, "request_invalid", "The platform account ID is invalid.")
        if platform == "instagram":
            account_id = account_id.casefold()
    if platform == "youtube" and account_id:
        canonical = f"https://www.youtube.com/channel/{account_id}"
    elif platform == "x" and account_id:
        canonical = f"https://x.com/i/user/{account_id}"
    else:
        canonical = profile_url or ""
    return account_id, canonical


class CreatorLibraryRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, creator_id, *, lock=False):
        query = (
            select(CreatorProfile)
            .where(CreatorProfile.id == creator_id)
            .options(
                selectinload(CreatorProfile.contacts),
                selectinload(CreatorProfile.works),
            )
        )
        if lock:
            acquire_job_change_lock(self.session)
            query = query.with_for_update().execution_options(populate_existing=True)
        creator = self.session.scalar(query)
        if creator is None:
            raise error(
                404, "creator_not_found", "The requested creator was not found."
            )
        return creator

    def _revision(self, creator, expected):
        if creator.manual_revision != expected:
            raise error(
                409,
                "creator_revision_conflict",
                "This creator was edited elsewhere. Reload before saving.",
            )

    def _unique(self, platform, account_id, exclude=None, canonical=""):
        if account_id is None and not canonical:
            return
        conditions = []
        if account_id is not None:
            conditions.append(CreatorProfile.platform_account_id == account_id)
        if platform == "youtube":
            if account_id is not None:
                conditions.append(CreatorProfile.youtube_channel_id == account_id)
        if canonical:
            conditions.append(CreatorProfile.canonical_url == canonical)
        query = select(CreatorProfile.id).where(
            CreatorProfile.platform == platform, or_(*conditions)
        )
        if exclude is not None:
            query = query.where(CreatorProfile.id != exclude)
        if self.session.scalar(query) is not None:
            raise error(
                409,
                "creator_identity_conflict",
                "This platform account already belongs to another creator.",
            )

    def create(self, value: CreatorCreate):
        acquire_job_change_lock(self.session)
        account, canonical = normalized_identity(
            value.platform, value.account_id, value.profile_url
        )
        self._unique(value.platform, account, canonical=canonical)
        fields = value.model_dump(mode="json", exclude_unset=True)
        creator = CreatorProfile(
            id=uuid4(),
            platform=value.platform,
            platform_account_id=account,
            youtube_channel_id=account if value.platform == "youtube" else None,
            canonical_url=canonical,
            sort_name=(value.name or value.profile_url or account or "")[:255],
            favorite=value.favorite,
            manual_overrides={
                k: v for k, v in fields.items() if k in CreatorFields.model_fields
            },
            manual_revision=1,
            manual_notes=value.internal_notes,
            current_facts={},
            analysis={},
            brief={},
            source_status={},
        )
        self.session.add(creator)
        self.session.flush()
        return creator

    def patch(self, creator_id, value: CreatorPatch):
        creator = self.get(creator_id, lock=True)
        self._revision(creator, value.expected_revision)
        fields = value.model_dump(mode="json", exclude_unset=True)
        manual = dict(creator.manual_overrides or {})
        for key in value.reset_fields:
            manual.pop(key, None)
        manual.update(
            {k: v for k, v in fields.items() if k in CreatorFields.model_fields}
        )
        creator.manual_overrides = manual
        if "internal_notes" in fields or "internal_notes" in value.reset_fields:
            creator.manual_notes = manual.get("internal_notes")
        # A changed public name is not confirmed by an older name's confirmation.
        if "public_name" in fields and "public_name_confirmed" not in fields:
            creator.manual_overrides = manual | {"public_name_confirmed": False}
        effective = effective_fields(creator)
        creator.sort_name = (
            effective.name
            or effective.profile_url
            or creator.platform_account_id
            or str(creator.id)
        )[:255]
        if "favorite" in fields:
            creator.favorite = value.favorite
        creator.manual_revision += 1
        self.session.flush()
        return creator

    def list(
        self,
        *,
        query,
        platform,
        language,
        only_collection,
        limit,
        offset,
        platforms=(),
        languages=(),
        sort="name",
    ):
        from app.repositories.library_queries import creator_sort_key
        from app.core.languages import language_keys

        stmt = select(CreatorProfile).options(
            selectinload(CreatorProfile.contacts), selectinload(CreatorProfile.works)
        )
        chosen_platforms = set(platforms) | ({platform} if platform else set())
        chosen_languages = language_keys([*languages, language])
        if chosen_platforms:
            stmt = stmt.where(CreatorProfile.platform.in_(chosen_platforms))
        if only_collection:
            stmt = stmt.where(CreatorProfile.favorite.is_(True))
        rows = self.session.scalars(stmt).all()
        items = []
        query = query.strip().casefold()
        for creator in rows:
            item = detail(creator)
            if chosen_languages and not chosen_languages.intersection(
                language_keys(item.languages)
            ):
                continue
            works = [
                work_detail(w, creator)
                for w in creator.works
                if w.identity_revision == creator.identity_revision
            ]
            text = " ".join(
                str(v or "")
                for v in [
                    item.name,
                    item.handle,
                    item.profile_url,
                    item.source_identity.account_id,
                    *[w.work_name or w.content_title for w in works],
                ]
            )
            if query and query not in text.casefold():
                continue
            items.append(item)
        items.sort(key=lambda v: creator_sort_key(v, sort, query))
        return CreatorPage(
            items=items[offset : offset + limit],
            total=len(items),
            limit=limit,
            offset=offset,
        )

    def rebind(self, creator_id, value: IdentityUpdate):
        from app.repositories.creator_identity import rebind_creator

        creator = self.get(creator_id, lock=True)
        self._revision(creator, value.expected_revision)
        account, canonical = normalized_identity(
            value.platform, value.account_id, value.profile_url
        )
        self._unique(value.platform, account, creator.id, canonical=canonical)
        old_revision = creator.identity_revision
        result = rebind_creator(
            self.session,
            creator,
            platform=value.platform,
            account_id=account,
            canonical_url=canonical,
            now=utc_now(),
        )
        if result.identity_revision != old_revision:
            manual = dict(result.manual_overrides or {})
            manual.pop("profile_url", None)
            manual.pop("handle", None)
            manual["public_name_confirmed"] = False
            if value.profile_url is not None:
                manual["profile_url"] = value.profile_url
            result.manual_overrides = manual
            self.session.flush()
        return result

    def _contact_duplicate(self, creator, email, active, exclude=None):
        if not active:
            return
        if any(
            c.id != exclude
            and c.is_active
            and c.identity_revision == creator.identity_revision
            and c.email.casefold() == str(email).casefold()
            for c in creator.contacts
        ):
            raise error(
                409,
                "creator_contact_conflict",
                "This email already exists for the current account.",
            )

    def add_contact(self, creator_id, value: ContactCreate):
        creator = self.get(creator_id, lock=True)
        self._revision(creator, value.expected_revision)
        self._contact_duplicate(creator, value.email, value.is_active)
        manual = value.model_dump(mode="json", exclude={"expected_revision"})
        contact = CreatorContact(
            creator_id=creator.id,
            email=str(value.email),
            purpose=value.purpose,
            source_url=value.source_url,
            source_type="manual",
            is_manual=True,
            is_active=value.is_active,
            validation_state="unverified",
            identity_revision=creator.identity_revision,
            source_fields={},
            manual_overrides=manual,
        )
        creator.contacts.append(contact)
        creator.manual_revision += 1
        self.session.flush()
        return creator

    def patch_contact(self, creator_id, contact_id, value: ContactPatch):
        creator = self.get(creator_id, lock=True)
        self._revision(creator, value.expected_revision)
        contact = next((c for c in creator.contacts if c.id == contact_id), None)
        if contact is None:
            raise error(
                404, "creator_contact_not_found", "The requested contact was not found."
            )
        if contact.identity_revision != creator.identity_revision:
            raise error(
                409,
                "creator_identity_changed",
                "A previous account contact cannot be edited as a current contact.",
            )
        manual = dict(contact.manual_overrides or {})
        if contact.is_manual and not manual:
            manual = {
                "email": contact.email,
                "purpose": contact.purpose,
                "source_url": contact.source_url,
                "is_active": contact.is_active,
            }
        source = dict(contact.source_fields or {})
        if not contact.is_manual and not source:
            source = {
                "email": contact.email,
                "purpose": contact.purpose,
                "source_url": contact.source_url,
                "is_active": contact.is_active,
                "validation_state": contact.validation_state,
            }
            contact.source_fields = source
        for key in value.reset_fields:
            manual.pop(key, None)
        manual.update(
            {
                k: v
                for k, v in value.model_dump(mode="json", exclude_unset=True).items()
                if k in ContactFields.model_fields
            }
        )
        merged = source | manual
        try:
            checked = ContactFields.model_validate(
                {k: v for k, v in merged.items() if k in ContactFields.model_fields}
            )
        except ValidationError:
            raise error(
                422, "request_invalid", "The contact requires a valid email."
            ) from None
        self._contact_duplicate(creator, checked.email, checked.is_active, contact.id)
        if "email" in value.model_fields_set:
            manual["validation_state"] = "unverified"
        if "email" in value.reset_fields:
            manual.pop("validation_state", None)
        contact.manual_overrides = manual
        contact.email = str(checked.email)
        contact.purpose = checked.purpose
        contact.source_url = checked.source_url
        contact.is_active = checked.is_active
        contact.validation_state = manual.get(
            "validation_state", source.get("validation_state", "unverified")
        )
        creator.manual_revision += 1
        self.session.flush()
        return creator

    def _validate_game(self, game_id):
        if game_id is not None and self.session.get(GameProfile, game_id) is None:
            raise error(422, "request_invalid", "The referenced game was not found.")

    def add_work(self, creator_id, value: WorkCreate):
        creator = self.get(creator_id, lock=True)
        self._validate_game(value.game_id)
        if creator.identity_revision != value.expected_identity_revision:
            raise error(
                409,
                "creator_identity_changed",
                "This account was rebound. Reload before adding evidence.",
            )
        work = CreatorWork(
            id=uuid4(),
            creator_id=creator.id,
            platform=value.platform or creator.platform,
            identity_revision=creator.identity_revision,
            origin="manual",
            source_content_id=None,
            source_fields={},
            manual_overrides=value.model_dump(
                mode="json", exclude={"expected_identity_revision"}
            ),
            revision=1,
        )
        self.session.add(work)
        self.session.flush()
        return work_detail(work, creator)

    def patch_work(self, creator_id, work_id, value: WorkPatch):
        creator = self.get(creator_id, lock=True)
        work = self.session.scalar(
            select(CreatorWork)
            .where(CreatorWork.id == work_id, CreatorWork.creator_id == creator.id)
            .with_for_update()
        )
        if work is None:
            raise error(
                404, "creator_work_not_found", "The requested work was not found."
            )
        if work.identity_revision != creator.identity_revision:
            raise error(
                409,
                "creator_identity_changed",
                "A previous account work cannot be edited as current evidence.",
            )
        if work.revision != value.expected_revision:
            raise error(
                409,
                "work_revision_conflict",
                "This work was edited elsewhere. Reload before saving.",
            )
        manual = dict(work.manual_overrides or {})
        for key in value.reset_fields:
            manual.pop(key, None)
        manual.update(
            {
                k: v
                for k, v in value.model_dump(mode="json", exclude_unset=True).items()
                if k in WorkFields.model_fields
            }
        )
        effective = WorkFields.model_validate(
            safe_fields(WorkFields, work.source_fields or {}).model_dump(mode="json")
            | manual
        )
        if (
            not effective.work_name
            and not effective.content_title
            and not effective.source_url
        ):
            raise error(
                422,
                "request_invalid",
                "A work/content title or source URL is required.",
            )
        self._validate_game(effective.game_id)
        work.manual_overrides = manual
        work.revision += 1
        self.session.flush()
        return work_detail(work, creator)

    def works(self, creator_id, *, include_previous_identity, limit, offset):
        creator = self.get(creator_id)
        works = [
            work_detail(w, creator)
            for w in creator.works
            if include_previous_identity
            or w.identity_revision == creator.identity_revision
        ]
        works.sort(
            key=lambda w: (
                (w.published_at.isoformat() if w.published_at else ""),
                str(w.id),
            ),
            reverse=True,
        )
        return WorkPage(
            items=works[offset : offset + limit],
            total=len(works),
            limit=limit,
            offset=offset,
        )
