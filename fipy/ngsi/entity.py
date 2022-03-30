"""
Basic NGSI v2 data types.
"""

from datetime import datetime
from pydantic import BaseModel, create_model
from typing import Any, List, Optional, Type

from fipy.dict import merge_dicts


def ld_urn(unique_suffix: str) -> str:
    return f"urn:ngsi-ld:{unique_suffix}"


class Attr(BaseModel):
    type: Optional[str]
    value: Any

    @classmethod
    def new(cls, value: Any) -> Optional['Attr']:
        if value is None:
            return None
        return cls(value=value)


class FloatAttr(Attr):
    type = 'Number'
    value: float


class TextAttr(Attr):
    type = 'Text'
    value: str


class BaseEntity(BaseModel):
    id: str
    type: str

    def set_id_with_type_prefix(self, unique_suffix: str):
        own_id = f"{self.type}:{unique_suffix}"
        self.id = ld_urn(own_id)
        return self

    def to_json(self) -> str:
        return self.json(exclude_none=True)

    @classmethod
    def from_raw(cls, raw_entity: dict) -> Optional['BaseEntity']:
        own_type = cls(id='').type
        etype = raw_entity.get('type', '')
        if own_type != etype:
            return None
        return cls(**raw_entity)


class EntityUpdateNotification(BaseModel):
    data: List[dict]

    def filter_entities(self, entity_class: Type[BaseEntity]) \
            -> List[BaseEntity]:
        candidates = [entity_class.from_raw(d) for d in self.data]
        return [c for c in candidates if c is not None]


class EntitiesUpsert(BaseModel):
    actionType = 'append'
    entities: List[BaseEntity]


class EntitySeries(BaseModel):
    """Time-indexed sequence of entity attribute values.
    This class defines the index, sub-classes fill in attribute values.

    Say you've defined an entity type `E:BaseEntity` with two attributes
    very creatively named `attr1` and `attr2`. You've also captured a
    time series of `E` instances of a specific ID
    ```
        t0, e0 = { id: aw42, type: E, attr1: v0, attr2: w0 }
        t1, e1 = { id: aw42, type: E, attr1: v1, attr2: w1 }
        t2, e2 = { id: aw42, type: E, attr1: v2, attr2: w2 }
    ```
    Then you could define an `EntitySeries` subclass to reshuffle the
    above data in a more data frame friendly format. The pattern is
    ```
        index: t0, t1, t2, ...
        attr1: v0, v1, v2, ...
        attr2: w0, w1, w2, ...
    ```
    where `v0` is the value of attribute `attr1` at time `t0`, `v1` is
    the value at time `t1`, and so on.

    So you'd define a sub-class like
    ```
        class ESeries(EntitySeries):
            attr1: List[int]
            attr2: List[float]
    ```
    create an instance from the original time series
    ```
        aw42_series = ESeries(
            index=[t0, t1, t2], attr1=[v0, v1, v2], attr2=[w0, w1, w2]
        )
    ```
    and then get a data frame friendly representation by calling the
    `dict` method. For example, here's how you'd get a properly time
    indexed Pandas frame out of the `aw42_series` above:
    ```
        data = aw42_series.dict()
        time_indexed_df = pd.DataFrame(data).set_index('index')
    ```
    Have a look at the test cases for more examples.
    """
    index: List[datetime]

    @classmethod
    def from_quantumleap_format(cls, entity_query_result: dict) \
            -> 'EntitySeries':
        """Convert an entity series returned by a Quantum Leap query to an
        `EntitySeries`.

        The returned object will have a field called `index` containing the
        time index array returned by Quantum Leap. Also, it will have a field
        for each returned attribute array and the field name will be the same
        as the attribute name.

        Args:
            entity_query_result: a dictionary representing the JSON object
                returned by a call to the `v2/entities/{entity ID}` Quantum
                Leap endpoint.
        """
        def to_kv(attr_payload: dict) -> dict:
            key = attr_payload.get('attrName', '')
            if key == '':
                return {}
            return {key: attr_payload.get('values', [])}

        attributes = entity_query_result.get('attributes', [])
        attr_fields = merge_dicts(*[to_kv(x) for x in attributes])

        raw_tix = entity_query_result.get('index', [])
        tix = [datetime.fromisoformat(t) for t in raw_tix]

        model_name = f"{entity_query_result.get('entityType', '')}Series"
        dynamic_model = create_model(model_name, __base__=cls, **attr_fields)
        return dynamic_model(index=tix)  # (*) see NOTE below

# NOTE. Pydantic default values.
# We create a dynamic Pydantic model to extend EntitySeries since we don't
# know the attribute names beforehand. So when creating the model we pass
# in the attribute names as field names. But we also stick in their values
# so Pydantic will use them as default values. As a result of that, if you
# access one of the attributes in the returned model instance, e.g. x.attr1,
# you'll get the corresponding value array returned by the Quantum Leap query.
# This is okay since the returned object is supposed to be immutable.
