from end_to_end_tests.functional_tests.helpers import (
    assert_model_decode_encode,
    assert_model_property_type_hint,
    with_generated_client_fixture,
    with_generated_code_imports,
)


@with_generated_client_fixture(
"""
components:
  schemas:
    StringOrInt:
      type: ["string", "integer"]
    MyModel:
      type: object
      properties:
        stringOrIntProp:
          type: ["string", "integer"]
"""
)
@with_generated_code_imports(
    ".models.MyModel",
)
class TestSimpleTypeList:
    def test_decode_encode(self, MyModel):
        assert_model_decode_encode(MyModel, {"stringOrIntProp": "a"}, MyModel(string_or_int_prop="a"))
        assert_model_decode_encode(MyModel, {"stringOrIntProp": 1}, MyModel(string_or_int_prop=1))

    def test_type_hints(self, MyModel):
        assert_model_property_type_hint(MyModel, "string_or_int_prop", "int | str | Unset")


@with_generated_client_fixture(
"""
components:
  schemas:
    ThingA:
      type: object
      properties:
        propA: { type: "string" }
      required: ["propA"]
    ThingB:
      type: object
      properties:
        propB: { type: "string" }
      required: ["propB"]
    ThingAOrB:
      oneOf:
        - $ref: "#/components/schemas/ThingA"
        - $ref: "#/components/schemas/ThingB"
    ModelWithUnion:
      type: object
      properties:
        thing: {"$ref": "#/components/schemas/ThingAOrB"}
        thingOrString:
          oneOf:
            - $ref: "#/components/schemas/ThingA"
            - type: string
    ModelWithRequiredUnion:
      type: object
      properties:
        thing: {"$ref": "#/components/schemas/ThingAOrB"}
      required: ["thing"]
    ModelWithNestedUnion:
      type: object
      properties:
        thingOrValue:
          oneOf:
            - "$ref": "#/components/schemas/ThingAOrB"
            - oneOf:
              - type: string
              - type: number
    ModelWithUnionOfOne:
      type: object
      properties:
        thing:
          oneOf:
            - $ref: "#/components/schemas/ThingA"
        requiredThing:
          oneOf:
            - $ref: "#/components/schemas/ThingA"
      required: ["requiredThing"]
""")
@with_generated_code_imports(
    ".models.ThingA",
    ".models.ThingB",
    ".models.ModelWithUnion",
    ".models.ModelWithRequiredUnion",
    ".models.ModelWithNestedUnion",
    ".models.ModelWithUnionOfOne",
)
class TestOneOf:
    def test_disambiguate_objects_via_required_properties(self, ThingA, ThingB, ModelWithUnion):
        assert_model_decode_encode(
            ModelWithUnion,
            {"thing": {"propA": "x"}},
            ModelWithUnion(thing=ThingA(prop_a="x")),
        )
        assert_model_decode_encode(
            ModelWithUnion,
            {"thing": {"propB": "x"}},
            ModelWithUnion(thing=ThingB(prop_b="x")),
        )

    def test_disambiguate_object_and_non_object(self, ThingA, ModelWithUnion):
        assert_model_decode_encode(
            ModelWithUnion,
            {"thingOrString": {"propA": "x"}},
            ModelWithUnion(thing_or_string=ThingA(prop_a="x")),
        )
        assert_model_decode_encode(
            ModelWithUnion,
            {"thingOrString": "x"},
            ModelWithUnion(thing_or_string="x"),
        )
    
    def test_disambiguate_nested_union(self, ThingA, ThingB, ModelWithNestedUnion):
        assert_model_decode_encode(
            ModelWithNestedUnion,
            {"thingOrValue": {"propA": "x"}},
            ModelWithNestedUnion(thing_or_value=ThingA(prop_a="x")),
        )
        assert_model_decode_encode(
            ModelWithNestedUnion,
            {"thingOrValue": 3},
            ModelWithNestedUnion(thing_or_value=3),
        )

    def test_type_hints(self, ModelWithUnion, ModelWithRequiredUnion, ModelWithUnionOfOne, ThingA):
        assert_model_property_type_hint(
            ModelWithUnion,
            "thing",
            "ThingA | ThingB | Unset",
        )
        assert_model_property_type_hint(
            ModelWithRequiredUnion,
            "thing",
            "ThingA | ThingB",
        )
        assert_model_property_type_hint(
            ModelWithUnionOfOne, "thing", "ThingA | Unset"
        )
        assert_model_property_type_hint(
            ModelWithUnionOfOne, "required_thing", "ThingA"
        )


@with_generated_client_fixture(
"""
components:
  schemas:
    NormalMember:
      type: object
      properties:
        type: { type: "string" }
        name: { type: "string" }
    CorpMember:
      type: object
      properties:
        type: { type: "string" }
        name: { type: "string" }
    Member:
      oneOf:
        - $ref: "#/components/schemas/NormalMember"
        - $ref: "#/components/schemas/CorpMember"
      discriminator:
        propertyName: "type"
        mapping:
          NormalMember: "#/components/schemas/NormalMember"
          CorporateMember: "#/components/schemas/CorpMember"
    AnyOfMember:
      anyOf:
        - $ref: "#/components/schemas/NormalMember"
        - $ref: "#/components/schemas/CorpMember"
      discriminator:
        propertyName: "type"
        mapping:
          NormalMember: "#/components/schemas/NormalMember"
          CorporateMember: "#/components/schemas/CorpMember"
    Post:
      type: object
      properties:
        author:
          $ref: "#/components/schemas/Member"
        anyOfAuthor:
          $ref: "#/components/schemas/AnyOfMember"
""")
@with_generated_code_imports(
    ".models.CorpMember",
    ".models.Member",
    ".models.NormalMember",
    ".models.Post",
)
class TestDiscriminatedOneOf:
    def test_uses_discriminator_mapping1(self, CorpMember, Post):
        talk = Post.from_dict({"author": {"type": "CorporateMember", "name": "Kim"}})

        assert talk.author == CorpMember(type_="CorporateMember", name="Kim")

    def test_uses_discriminator_mapping2(self, NormalMember, Post):
        talk = Post.from_dict({"author": {"type": "NormalMember", "name": "Kim"}})

        assert talk.author == NormalMember(type_="NormalMember", name="Kim")

    def test_uses_any_of_discriminator_mapping(self, CorpMember, Post):
        post = Post.from_dict({"anyOfAuthor": {"type": "CorporateMember", "name": "Kim"}})

        assert post.any_of_author == CorpMember(type_="CorporateMember", name="Kim")

    def test_unknown_discriminator_value_fails(self, Post):
        try:
            Post.from_dict({"author": {"type": "CorpMember", "name": "Kim"}})
        except ValueError as error:
            assert "Unexpected discriminator value" in str(error)
        else:
            raise AssertionError("Expected unknown discriminator values to fail")
