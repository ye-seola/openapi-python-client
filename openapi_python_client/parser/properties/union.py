from __future__ import annotations

from collections.abc import Iterator
from itertools import chain
from typing import Any, ClassVar, cast

from attr import define, evolve

from ... import Config
from ... import schema as oai
from ...utils import PythonIdentifier
from ..errors import ParseError, PropertyError
from .protocol import PropertyProtocol, Value
from .schemas import ReferencePath, Schemas, get_reference_simple_name, parse_reference_path


@define
class UnionProperty(PropertyProtocol):
    """A property representing a Union (anyOf) of other properties"""

    name: str
    required: bool
    default: Value | None
    python_name: PythonIdentifier
    description: str | None
    example: str | None
    inner_properties: list[PropertyProtocol]
    discriminator_property_name: str | None = None
    discriminator_mapping: dict[str, PropertyProtocol] | None = None
    template: ClassVar[str] = "union_property.py.jinja"

    @classmethod
    def build(
        cls,
        *,
        data: oai.Schema,
        name: str,
        required: bool,
        schemas: Schemas,
        parent_name: str,
        config: Config,
    ) -> tuple[UnionProperty | PropertyError, Schemas]:
        """
        Create a `UnionProperty` the right way.

        Args:
            data: The `Schema` describing the `UnionProperty`.
            name: The name of the property where it appears in the OpenAPI document.
            required: Whether this property is required where it's being used.
            schemas: The `Schemas` so far describing existing classes / references.
            parent_name: The name of the thing which holds this property (used for renaming inner classes).
            config: User-defined config values for modifying inner properties.

        Returns:
            `(result, schemas)` where `schemas` is the updated version of the input `schemas` and `result` is the
                constructed `UnionProperty` or a `PropertyError` describing what went wrong.
        """
        from . import property_from_data  # noqa: PLC0415

        sub_properties: list[PropertyProtocol] = []

        type_list_data = []
        if isinstance(data.type, list):
            for _type in data.type:
                type_list_data.append(data.model_copy(update={"type": _type, "default": None}))

        sub_properties_by_ref_path: dict[ReferencePath, PropertyProtocol] = {}
        for i, sub_prop_data in enumerate(chain(data.anyOf, data.oneOf, type_list_data)):
            # If a schema has a unique title property, we can use that to carry forward a descriptive name instead of "type_0"
            subscript: str
            if (
                isinstance(sub_prop_data, oai.Schema)
                and sub_prop_data.title is not None
                and sub_prop_data.title != data.title
            ):
                subscript = sub_prop_data.title
            else:
                subscript = f"type_{i}"

            sub_prop, schemas = property_from_data(
                name=f"{name}_{subscript}",
                required=True,
                data=sub_prop_data,
                schemas=schemas,
                parent_name=parent_name,
                config=config,
            )
            if isinstance(sub_prop, PropertyError):
                return (
                    PropertyError(detail=f"Invalid property in union {name}", data=sub_prop_data),
                    schemas,
                )
            sub_property = cast(PropertyProtocol, sub_prop)
            if isinstance(sub_prop_data, oai.Reference):
                ref_path = parse_reference_path(sub_prop_data.ref)
                if isinstance(ref_path, ParseError):
                    return PropertyError(detail=ref_path.detail, data=sub_prop_data), schemas
                sub_properties_by_ref_path[ref_path] = sub_property
            sub_properties.append(sub_property)

        def flatten_union_properties(possibly_nested: list[PropertyProtocol]) -> Iterator[PropertyProtocol]:
            for to_flatten in possibly_nested:
                if isinstance(to_flatten, UnionProperty):
                    yield from flatten_union_properties(to_flatten.inner_properties)
                else:
                    yield to_flatten

        seen_types = set()
        inner_properties: list[PropertyProtocol] = []
        for flattened in flatten_union_properties(sub_properties):
            type_string = flattened.get_type_string(no_optional=True)
            if type_string not in seen_types:
                seen_types.add(type_string)
                inner_properties.append(flattened)

        discriminator_mapping = _get_discriminator_mapping(data, sub_properties_by_ref_path)
        if isinstance(discriminator_mapping, PropertyError):
            return discriminator_mapping, schemas

        prop = UnionProperty(
            name=name,
            required=required,
            default=None,
            inner_properties=inner_properties,
            discriminator_property_name=data.discriminator.propertyName if data.discriminator is not None else None,
            discriminator_mapping=discriminator_mapping,
            python_name=PythonIdentifier(value=name, prefix=config.field_prefix),
            description=data.description,
            example=data.example,
        )
        default_or_error = prop.convert_value(data.default)
        if isinstance(default_or_error, PropertyError):
            default_or_error.data = data
            return default_or_error, schemas
        prop = evolve(prop, default=default_or_error)
        return prop, schemas

    def convert_value(self, value: Any) -> Value | None | PropertyError:
        if value is None or isinstance(value, Value):
            return None
        value_or_error: Value | PropertyError | None = PropertyError(
            detail=f"Invalid default value for union {self.name}"
        )
        for sub_prop in self.inner_properties:
            value_or_error = sub_prop.convert_value(value)
            if not isinstance(value_or_error, PropertyError):
                return value_or_error
        return value_or_error

    def _get_inner_type_strings(self, json: bool) -> set[str]:
        return {
            p.get_type_string(
                no_optional=True,
                json=json,
            )
            for p in self.inner_properties
        }

    @staticmethod
    def _get_type_string_from_inner_type_strings(inner_types: set[str]) -> str:
        if len(inner_types) == 1:
            return inner_types.pop()
        return " | ".join(sorted(inner_types, key=lambda x: x.lower()))

    def get_base_type_string(self) -> str:
        return self._get_type_string_from_inner_type_strings(self._get_inner_type_strings(json=False))

    def get_base_json_type_string(self) -> str:
        return self._get_type_string_from_inner_type_strings(self._get_inner_type_strings(json=True))

    def get_type_strings_in_union(self, *, no_optional: bool = False, json: bool) -> set[str]:
        """
        Get the set of all the types that should appear within the `Union` representing this property.

        This function is called from the union property macros, thus the public visibility.

        Args:
            no_optional: Do not include `None` or `Unset` in this set.
            json: If True, this returns the JSON types, not the Python types, of this property.

        Returns:
            A set of strings containing the types that should appear within `Union`.
        """
        type_strings = self._get_inner_type_strings(json=json)
        if no_optional:
            return type_strings
        if not self.required:
            type_strings.add("Unset")
        return type_strings

    def get_type_string(
        self,
        no_optional: bool = False,
        json: bool = False,
    ) -> str:
        """
        Get a string representation of type that should be used when declaring this property.
        This implementation differs slightly from `Property.get_type_string` in order to collapse
        nested union types.
        """
        type_strings_in_union = self.get_type_strings_in_union(no_optional=no_optional, json=json)
        return self._get_type_string_from_inner_type_strings(type_strings_in_union)

    def get_imports(self, *, prefix: str) -> set[str]:
        """
        Get a set of import strings that should be included when this property is used somewhere

        Args:
            prefix: A prefix to put before any relative (local) module names. This should be the number of . to get
            back to the root of the generated client.
        """
        imports = super().get_imports(prefix=prefix)
        for inner_prop in self.inner_properties:
            imports.update(inner_prop.get_imports(prefix=prefix))
        imports.add("from typing import cast")
        return imports

    def get_lazy_imports(self, *, prefix: str) -> set[str]:
        lazy_imports = super().get_lazy_imports(prefix=prefix)
        for inner_prop in self.inner_properties:
            lazy_imports.update(inner_prop.get_lazy_imports(prefix=prefix))
        return lazy_imports

    def validate_location(self, location: oai.ParameterLocation) -> ParseError | None:
        """Returns an error if this type of property is not allowed in the given location"""
        from ..properties import Property  # noqa: PLC0415

        for inner_prop in self.inner_properties:
            if evolve(cast(Property, inner_prop), required=self.required).validate_location(location) is not None:
                return ParseError(detail=f"{self.get_type_string()} is not allowed in {location}")
        return None


def _get_discriminator_mapping(
    data: oai.Schema, sub_properties_by_ref_path: dict[ReferencePath, PropertyProtocol]
) -> dict[str, PropertyProtocol] | None | PropertyError:
    if data.discriminator is None:
        return None

    if data.discriminator.mapping is None:
        return {
            get_reference_simple_name(ref_path): sub_prop for ref_path, sub_prop in sub_properties_by_ref_path.items()
        }

    discriminator_mapping: dict[str, PropertyProtocol] = {}
    for discriminator_value, ref in data.discriminator.mapping.items():
        ref_path = parse_reference_path(ref)
        if isinstance(ref_path, ParseError):
            return PropertyError(detail=ref_path.detail, data=data)

        sub_prop = sub_properties_by_ref_path.get(ref_path)
        if sub_prop is not None:
            discriminator_mapping[discriminator_value] = sub_prop

    return discriminator_mapping
