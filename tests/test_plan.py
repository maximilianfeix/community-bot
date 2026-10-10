from __future__ import annotations

from communitybot.definition import SERVER, CategorySpec, ChannelSpec, RoleSpec, ServerSpec
from communitybot.plan import (
    Conflict,
    CreateCategory,
    CreateChannel,
    CreateRole,
    EditChannel,
    Observed,
    ObservedChannel,
    RenameCategory,
    RenameRole,
    plan,
)

SPEC = ServerSpec(
    roles=(RoleSpec("role:a", "a releases", 0x123456),),
    categories=(
        CategorySpec(
            "category:info",
            "info",
            (
                ChannelSpec("channel:welcome", "welcome", "Start here.", read_only=True),
                ChannelSpec("channel:general", "general", "Talk."),
            ),
        ),
    ),
)

OWNED = {"role:a": 10, "category:info": 20, "channel:welcome": 30, "channel:general": 31}


def in_sync() -> Observed:
    return Observed(
        roles={10: "a releases"},
        categories={20: "info"},
        channels={
            30: ObservedChannel("welcome", "Start here.", 20, True),
            31: ObservedChannel("general", "Talk.", 20, False),
        },
    )


def test_empty_server_gets_everything_created_in_dependency_order() -> None:
    assert plan(SPEC, Observed(), {}) == [
        CreateRole("role:a", "a releases"),
        CreateCategory("category:info", "info"),
        CreateChannel("channel:welcome", "category:info", "welcome", "Start here.", True),
        CreateChannel("channel:general", "category:info", "general", "Talk.", False),
    ]


def test_server_in_sync_needs_nothing() -> None:
    assert plan(SPEC, in_sync(), OWNED) == []


def test_running_twice_is_idempotent() -> None:
    assert plan(SPEC, in_sync(), OWNED) == plan(SPEC, in_sync(), OWNED) == []


def test_owned_things_are_renamed_back() -> None:
    observed = Observed(
        roles={10: "renamed"},
        categories={20: "INFO!"},
        channels={
            30: ObservedChannel("hello", "Start here.", 20, True),
            31: ObservedChannel("general", "Talk.", 20, False),
        },
    )
    assert plan(SPEC, observed, OWNED) == [
        RenameRole("role:a", 10, "a releases"),
        RenameCategory("category:info", 20, "info"),
        EditChannel("channel:welcome", 30, name="welcome"),
    ]


def test_topic_and_read_only_are_fixed_independently() -> None:
    observed = Observed(
        roles={10: "a releases"},
        categories={20: "info"},
        channels={
            30: ObservedChannel("welcome", "old topic", 20, False),
            31: ObservedChannel("general", "Talk.", 20, True),
        },
    )
    assert plan(SPEC, observed, OWNED) == [
        EditChannel("channel:welcome", 30, topic="Start here.", read_only=True),
        EditChannel("channel:general", 31, read_only=False),
    ]


def test_channel_dragged_elsewhere_is_moved_back() -> None:
    observed = Observed(
        roles={10: "a releases"},
        categories={20: "info", 99: "other"},
        channels={
            30: ObservedChannel("welcome", "Start here.", 99, True),
            31: ObservedChannel("general", "Talk.", None, False),
        },
    )
    assert plan(SPEC, observed, OWNED) == [
        EditChannel("channel:welcome", 30, move_to_category_key="category:info"),
        EditChannel("channel:general", 31, move_to_category_key="category:info"),
    ]


def test_deleted_owned_things_are_recreated() -> None:
    observed = Observed(
        roles={}, categories={20: "info"}, channels={31: ObservedChannel("general", "Talk.", 20, False)}
    )
    assert plan(SPEC, observed, OWNED) == [
        CreateRole("role:a", "a releases"),
        CreateChannel("channel:welcome", "category:info", "welcome", "Start here.", True),
    ]


def test_deleted_category_is_recreated_and_its_channels_moved_into_it() -> None:
    observed = Observed(
        roles={10: "a releases"},
        categories={},
        channels={
            30: ObservedChannel("welcome", "Start here.", None, True),
            31: ObservedChannel("general", "Talk.", None, False),
        },
    )
    assert plan(SPEC, observed, OWNED) == [
        CreateCategory("category:info", "info"),
        EditChannel("channel:welcome", 30, move_to_category_key="category:info"),
        EditChannel("channel:general", 31, move_to_category_key="category:info"),
    ]


class TestForeignThingsAreLeftAlone:
    def test_foreign_role_with_our_name_is_a_conflict_not_adopted(self) -> None:
        observed = Observed(roles={555: "A Releases"})
        operations = plan(SPEC, observed, {})
        assert operations[0] == Conflict("role:a", "a role named 'a releases' exists and is not ours")
        assert not any(isinstance(op, CreateRole | RenameRole) for op in operations)

    def test_foreign_channel_with_our_name_is_a_conflict(self) -> None:
        observed = Observed(channels={777: ObservedChannel("general", "", None, False)})
        operations = plan(SPEC, observed, {})
        assert Conflict("channel:general", "a channel named 'general' exists and is not ours") in operations
        assert CreateChannel("channel:welcome", "category:info", "welcome", "Start here.", True) in operations

    def test_foreign_category_blocks_its_channels_too(self) -> None:
        observed = Observed(categories={888: "info"})
        operations = plan(SPEC, observed, {})
        assert [type(op) for op in operations] == [CreateRole, Conflict, Conflict, Conflict]
        assert {op.key for op in operations if isinstance(op, Conflict)} == {
            "category:info",
            "channel:welcome",
            "channel:general",
        }

    def test_no_operation_ever_refers_to_an_id_we_do_not_own(self) -> None:
        observed = Observed(
            roles={1: "x", 2: "a releases"},
            categories={3: "info", 4: "proxy-scraper"},
            channels={5: ObservedChannel("welcome", "", 3, False), 6: ObservedChannel("about", "", 4, True)},
        )
        touched = [
            getattr(op, name)
            for op in plan(SPEC, observed, {})
            for name in ("role_id", "category_id", "channel_id")
            if hasattr(op, name)
        ]
        assert touched == []

    def test_the_other_bots_category_is_never_part_of_a_plan(self) -> None:
        observed = Observed(
            categories={4: "proxy-scraper"},
            channels={6: ObservedChannel("about", "", 4, True), 7: ObservedChannel("commands", "", 4, False)},
        )
        operations = plan(SERVER, observed, {})
        assert not any(isinstance(op, Conflict) for op in operations)
        assert all(not isinstance(op, EditChannel | RenameCategory) for op in operations)


def test_the_real_definition_plans_cleanly_on_an_empty_server() -> None:
    operations = plan(SERVER, Observed(), {})
    assert not any(isinstance(op, Conflict) for op in operations)
    created = [op.key for op in operations if isinstance(op, CreateChannel)]
    assert created == list(SERVER.channel_keys())
