from collections import defaultdict
from itertools import chain, filterfalse
from io import BytesIO
import re
from toposort import toposort_flatten
from typing import Callable, Dict, List, IO, Iterator, Set, Union

import attr

from lxml import etree

from cassis.util import is_file_like

PREDEFINED_TYPES = {
    'uima.cas.TOP',
    'uima.cas.Integer',
    'uima.cas.Float',
    'uima.cas.String',
    'uima.cas.ArrayBase',
    'uima.cas.FSArray',
    'uima.cas.FloatArray',
    'uima.cas.IntegerArray',
    'uima.cas.StringArray',
    'uima.cas.ListBase',
    'uima.cas.FSList',
    'uima.cas.EmptyFSList',
    'uima.cas.NonEmptyFSList',
    'uima.cas.FloatList',
    'uima.cas.EmptyFloatList',
    'uima.cas.NonEmptyFloatList',
    'uima.cas.IntegerList',
    'uima.cas.EmptyIntegerList',
    'uima.cas.NonEmptyIntegerList',
    'uima.cas.StringList',
    'uima.cas.EmptyStringList',
    'uima.cas.NonEmptyStringList',
    'uima.cas.Boolean',
    'uima.cas.Byte',
    'uima.cas.Short',
    'uima.cas.Long',
    'uima.cas.Double',
    'uima.cas.BooleanArray',
    'uima.cas.ByteArray',
    'uima.cas.ShortArray',
    'uima.cas.LongArray',
    'uima.cas.DoubleArray',
    'uima.cas.Sofa',
    'uima.cas.AnnotationBase',
    'uima.tcas.Annotation',
}


def _string_to_valid_classname(name: str):
    return re.sub('[^a-zA-Z_]', '_', name)


@attr.s(slots=True)
class AnnotationBase:
    type: str = attr.ib()
    xmiID: int = attr.ib(default=None)


@attr.s(slots=True)
class Feature:
    name: str = attr.ib()
    rangeTypeName: str = attr.ib()
    description: str = attr.ib(default=None)
    elementType: str = attr.ib(default=None)
    multipleReferencesAllowed: bool = attr.ib(default=None)


@attr.s(slots=True)
class Type:
    name: str = attr.ib()
    supertypeName: str = attr.ib()
    children: Set[str] = attr.ib(factory=set)
    features: Dict[str, Feature] = attr.ib(factory=dict)
    description: str = attr.ib(default=None)
    _inherited_features: Dict[str, Feature] = attr.ib(factory=dict)
    _constructor: Callable[[Dict], AnnotationBase] = attr.ib(init=False, cmp=False, repr=False)

    def __attrs_post_init__(self):
        """ Build the constructor that can create annotations of this type """
        name = _string_to_valid_classname(self.name)
        fields = {feature.name: attr.ib(default=None) for feature in chain(self.features.values(),
                                                                           self._inherited_features.values())}
        fields['type'] = attr.ib(default=self.name)

        self._constructor = attr.make_class(name, fields, bases=(AnnotationBase,), slots=True)

    def __call__(self, **kwargs) -> AnnotationBase:
        """ Creates an annotation of this type """
        return self._constructor(**kwargs)

    def get_feature(self, name: str) -> Feature:
        """ Find a feature by name

        This returns `None` if this type does not contain a feature
        with the given `name`.

        Args:
            name: The name of the feature

        Returns:
            The feature with name `name` or `None` if it does not exist.
        """
        return self.features.get(name, None)

    def add_feature(self, feature: Feature, inherited: bool = False):
        """ Add the given feature to his type.

        Args:
            feature: The feature
            inherited: Indicates whether this feature is inherited from a parent or not

        """
        target = self.features if not inherited else self._inherited_features

        if feature.name in target:
            msg = 'Feature with name [{0}] already exists in [{1}]!'.format(feature.name, self.name)
            raise ValueError(msg)
        target[feature.name] = feature

        # Recreate constructor to incorporate new features
        self.__attrs_post_init__()

    @property
    def all_features(self) -> Iterator[Feature]:
        return chain(self.features.values(), self._inherited_features.values())


class TypeSystem:
    TOP_TYPE_NAME = 'uima.cas.TOP'

    def __init__(self):
        self._types = {}

        # The type system of a UIMA CAS has several predefined types. These are
        # added in the following

        # `top` is directly assigned in order to circumvent the inheritance
        top = Type(name=TypeSystem.TOP_TYPE_NAME, supertypeName=None)
        self._types[top.name] = top

        # Primitive types
        self.create_type(name='uima.cas.Boolean', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Byte', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Short', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Long', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Double', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Integer', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.Float', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.String', supertypeName='uima.cas.TOP')

        # Array
        self.create_type(name='uima.cas.ArrayBase', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.FSArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.BooleanArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.ByteArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.ShortArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.LongArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.DoubleArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.FloatArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.IntegerArray', supertypeName='uima.cas.ArrayBase')
        self.create_type(name='uima.cas.StringArray', supertypeName='uima.cas.ArrayBase')

        # List
        self.create_type(name='uima.cas.ListBase', supertypeName='uima.cas.TOP')
        self.create_type(name='uima.cas.FSList', supertypeName='uima.cas.ListBase')
        self.create_type(name='uima.cas.EmptyFSList', supertypeName='uima.cas.FSList')
        t = self.create_type(name='uima.cas.NonEmptyFSList', supertypeName='uima.cas.FSList')
        self.add_feature(t, name='head', rangeTypeName='uima.cas.TOP', multipleReferencesAllowed=True)
        self.add_feature(t, name='tail', rangeTypeName='uima.cas.FSList', multipleReferencesAllowed=True)

        # FloatList
        self.create_type(name='uima.cas.FloatList', supertypeName='uima.cas.ListBase')
        self.create_type(name='uima.cas.EmptyFloatList', supertypeName='uima.cas.FloatList')
        t = self.create_type(name='uima.cas.NonEmptyFloatList', supertypeName='uima.cas.FloatList')
        self.add_feature(t, name='head', rangeTypeName='uima.cas.Float')
        self.add_feature(t, name='tail', rangeTypeName='uima.cas.FloatList', multipleReferencesAllowed=True)

        # IntegerList
        self.create_type(name='uima.cas.IntegerList', supertypeName='uima.cas.ListBase')
        self.create_type(name='uima.cas.EmptyIntegerList', supertypeName='uima.cas.IntegerList')
        t = self.create_type(name='uima.cas.NonEmptyIntegerList', supertypeName='uima.cas.IntegerList')
        self.add_feature(t, name='head', rangeTypeName='uima.cas.Integer')
        self.add_feature(t, name='tail', rangeTypeName='uima.cas.IntegerList', multipleReferencesAllowed=True)

        # StringList
        self.create_type(name='uima.cas.StringList', supertypeName='uima.cas.ListBase')
        self.create_type(name='uima.cas.EmptyStringList', supertypeName='uima.cas.StringList')
        t = self.create_type(name='uima.cas.NonEmptyStringList', supertypeName='uima.cas.StringList')
        self.add_feature(t, name='head', rangeTypeName='uima.cas.String')
        self.add_feature(t, name='tail', rangeTypeName='uima.cas.StringList', multipleReferencesAllowed=True)

        # Sofa
        t = self.create_type(name='uima.cas.Sofa', supertypeName='uima.cas.TOP')
        self.add_feature(t, name='sofaNum', rangeTypeName='uima.cas.Integer')
        self.add_feature(t, name='sofaID', rangeTypeName='uima.cas.String')
        self.add_feature(t, name='mimeType', rangeTypeName='uima.cas.String')
        self.add_feature(t, name='sofaArray', rangeTypeName='uima.cas.TOP', multipleReferencesAllowed=True)
        self.add_feature(t, name='sofaString', rangeTypeName='uima.cas.String')
        self.add_feature(t, name='sofaURI', rangeTypeName='uima.cas.String')

        # AnnotationBase
        t = self.create_type(name='uima.cas.AnnotationBase', supertypeName='uima.cas.TOP')
        self.add_feature(t, name='sofa', rangeTypeName='uima.cas.Sofa')

        # Annotation
        t = self.create_type(name='uima.tcas.Annotation', supertypeName='uima.cas.AnnotationBase')
        self.add_feature(t, name='begin', rangeTypeName='uima.cas.Integer')
        self.add_feature(t, name='end', rangeTypeName='uima.cas.Integer')

    def has_type(self, typename: str):
        """

        Args:
            typename (str):

        Returns:

        """
        return typename in self._types

    def create_type(self, name: str, supertypeName: str = 'uima.tcas.Annotation', description: str = None) -> Type:
        """ Create a new type and return it.

        Args:
            name: The name of the new type
            supertypeName: The name of the new types' supertype. Defaults to `uima.cas.AnnotationBase`
            description: The description of the new type

        Returns:
            The newly created type
        """
        if self.has_type(name):
            msg = 'Type with name [{0}] already exists!'.format(name)
            raise ValueError(msg)

        new_type = Type(name=name, supertypeName=supertypeName, description=description)

        if supertypeName != TypeSystem.TOP_TYPE_NAME:
            supertype = self.get_type(supertypeName)
            supertype.children.add(name)

            for feature in supertype.all_features:
                new_type.add_feature(feature, inherited=True)

        self._types[name] = new_type
        return new_type

    def get_type(self, typename: str) -> Type:
        """

        Args:
            typename (str):

        Returns:

        """
        if self.has_type(typename):
            return self._types[typename]
        else:
            raise Exception('Type with name [{0}] not found!'.format(typename))

    def get_types(self) -> Iterator[Type]:
        """ Returns all types of this type system """
        return filterfalse(lambda x: x.name in PREDEFINED_TYPES, self._types.values())

    def add_feature(self, type_: Type, name: str, rangeTypeName: str, elementType: str = None,
                    description: str = None,  multipleReferencesAllowed: bool = None):
        feature = Feature(name=name, rangeTypeName=rangeTypeName,  elementType=elementType,
                          description=description, multipleReferencesAllowed=multipleReferencesAllowed)
        type_.add_feature(feature)

        for child_name in type_.children:
            child_type = self.get_type(child_name)
            child_type.add_feature(feature, inherited=True)

    def to_xml(self, path_or_buf: Union[IO, str] = None):
        """ Creates a string representation of this type system

        Args:
            path_or_buf: File path or file-like object, if None is provided the result is returned as a string.

        Returns:

        """
        serializer = TypeSystemSerializer()

        if path_or_buf is None:
            sink = BytesIO()
            serializer.serialize(sink, self)
            return sink.getvalue().decode('utf-8')
        elif is_file_like(path_or_buf):
            serializer.serialize(path_or_buf, self)
        else:
            with open(path_or_buf, 'wb') as f:
                serializer.serialize(f, self)

# Deserializing


def load_typesystem(source: Union[IO, str]) -> TypeSystem:
    deserializer = TypeSystemDeserializer()
    if isinstance(source, str):
        return deserializer.deserialize(BytesIO(source.encode('utf-8')))
    else:
        return deserializer.deserialize(source)


class TypeSystemDeserializer:

    def deserialize(self, source: Union[IO, str]) -> TypeSystem:
        """

        Args:
            source: a filename or file object containing XML data

        Returns:
            typesystem (TypeSystem):
        """

        # It can be that the types in the xml are listed out-of-order, that means
        # some type A appears before its supertype. In order to deserialize these
        # files properly without sacrificing the requirement that the supertype
        # of a type needs to already be present, we sort the graph of types and
        # supertypes topologically. This means a supertype will always be inserted
        # before its children. The inheritance relation is expressed in the
        # `dependencies` dictionary.
        types = {}
        features = defaultdict(list)
        dependencies = defaultdict(set)

        context = etree.iterparse(source, events=('end',), tag=('{*}typeDescription',))
        for event, elem in context:
            type_name = self._get_elem_text(elem.find('{*}name'))
            description = self._get_elem_text(elem.find('{*}description'))
            supertypeName = self._get_elem_text(elem.find('{*}supertypeName'))

            types[type_name] = Type(name=type_name, supertypeName=supertypeName, description=description)
            dependencies[type_name].add(supertypeName)

            # Parse features
            for fd in elem.iterfind('{*}features/{*}featureDescription'):
                feature_name = self._get_elem_text(fd.find('{*}name'))
                rangeTypeName = self._get_elem_text(fd.find('{*}rangeTypeName'))
                elementType = self._get_elem_text(fd.find('{*}elementType'))
                description = self._get_elem_text(fd.find('{*}description'))

                f = Feature(name=feature_name, rangeTypeName=rangeTypeName,
                            elementType=elementType, description=description)
                features[type_name].append(f)

                # The feature range also uses type information which has to
                # be included in the dependency relation
                dependencies[type_name].add(rangeTypeName)

            # Free the XML tree element from memory as it is not needed anymore
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
        del context

        ts = TypeSystem()
        for type_name in toposort_flatten(dependencies, sort=False):
            # No need to create predefined types
            if type_name in PREDEFINED_TYPES:
                continue

            t = types[type_name]
            created_type = ts.create_type(name=t.name, description=t.description, supertypeName=t.supertypeName)

            for f in features[t.name]:
                ts.add_feature(created_type, name=f.name, rangeTypeName=f.rangeTypeName,
                               elementType=f.elementType, description=f.description)

        return ts

    def _get_elem_text(self, elem: etree.Element) -> str:
        if elem is not None:
            return elem.text
        else:
            return None


# Serializing

class TypeSystemSerializer:

    def serialize(self, sink: Union[IO, str], typesystem: TypeSystem):
        nsmap = {None: 'http://uima.apache.org/resourceSpecifier'}
        with etree.xmlfile(sink) as xf:
            with xf.element('typeSystemDescription', nsmap=nsmap):
                with xf.element('types'):
                    for type in sorted(typesystem.get_types(), key=lambda t: t.name):
                        self._serialize_type(xf, type)

    def _serialize_type(self, xf: IO, type: Type):
        typeDescription = etree.Element('typeDescription')

        name = etree.SubElement(typeDescription, 'name')
        name.text = type.name

        description = etree.SubElement(typeDescription, 'description')
        description.text = type.description

        supertypeName = etree.SubElement(typeDescription, 'supertypeName')
        supertypeName.text = type.supertypeName

        # Only create `feature` element if there is at least one feature
        feature_list = list(type.features.values())
        if feature_list:
            features = etree.SubElement(typeDescription, 'features')
            for feature in feature_list:
                self._serialize_feature(features, feature)

        xf.write(typeDescription)

    def _serialize_feature(self, features: etree.Element, feature: Feature):
        featureDescription = etree.SubElement(features, 'featureDescription')

        name = etree.SubElement(featureDescription, 'name')
        name.text = feature.name

        description = etree.SubElement(featureDescription, 'description')
        description.text = feature.description

        rangeTypeName = etree.SubElement(featureDescription, 'rangeTypeName')
        rangeTypeName.text = feature.rangeTypeName

        if feature.elementType is not None:
            elementType = etree.SubElement(featureDescription, 'elementType')
            elementType.text = feature.elementType