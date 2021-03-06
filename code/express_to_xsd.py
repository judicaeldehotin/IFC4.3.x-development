import re
import sys
import itertools

import xml_dict

from dataclasses import dataclass

from append_xmi import namespace
from ifcopenshell.express import express_parser
from xmi_document import SCHEMA_NAME

def flatmap(func, *iterable):
    return itertools.chain.from_iterable(map(func, *iterable))

namespaces = {
    'xs': "http://www.w3.org/2001/XMLSchema",
    'xlink': "http://www.w3.org/1999/xlink",
    'ifc': f"https://standards.buildingsmart.org/IFC/RELEASE/{'/'.join(re.split('_|X', SCHEMA_NAME))}"
}

conf = xml_dict.read("IFC4_conf.xml")
entity_configuration = {
    c.attributes['select']:\
    {cc.attributes['select']:cc.attributes for cc in c.children if cc.tag.endswith('attribute') or cc.tag.endswith('inverse') } \
    for c in conf.children if c.tag.endswith('entity')
}

XS = namespace(namespaces['xs'])
XLINK = namespace(namespaces['xlink'])
IFC = namespace(namespaces['ifc'])

class xml_serializable:
    def to_xml(self):
        return xml_dict.xml_node(getattr(XS, self.__dict__.get('tagname', type(self).__name__)), {k:v for k, v in self.__dict__.items() if v and k != 'tagname'})
    

@dataclass
class attribute(xml_serializable):
    name : str
    type : str = None
    use : str = "optional"


@dataclass
class attribute_ref(xml_serializable):
    ref : str
    fixed : str = None
    use : str = "optional"
    
    tagname : str = "attribute"


@dataclass
class element(xml_serializable):
    name : str
    type : str = None
    abstract : str = None
    minOccurs : str = "0"
    substitutionGroup : str = None
    nillable : str = None
    

@dataclass
class element_ref(xml_serializable):
    ref : str
    minOccurs : str = None
    maxOccurs : str = None
    
    tagname : str = "element"
    

def complex_type(elements, attributes, content=None, **kwargs):
    if content:
        children = [content]
    else:
        children = [
            xml_dict.xml_node(
                XS.sequence,
                children=elements
            )
        ]
    return xml_dict.xml_node(
        XS.complexType,
        kwargs,
        children=children + list(map(attribute.to_xml, attributes))
    )

def do_try(fn):
    try:
        return fn()
    except:
        pass

def create_attribute(entity, a):
    a_type = a.type
    
    is_optional = a.optional
    
    if isinstance(a_type, express_parser.NamedType):
        ty = a_type.type
        
        is_binary = do_try(lambda: isinstance(schema.types[ty].type.type, express_parser.BinaryType))
        
        if ty in schema.entities or is_binary:
            assert isinstance(ty, str)
            return element(a.name, f"ifc:{ty}", nillable=None if is_binary else "true", minOccurs="0" if is_optional else None).to_xml()
        elif ty in schema.selects:
            assert isinstance(ty, str)
            elm = element(a.name, None, nillable="true" if is_optional else None, minOccurs="0" if is_optional else None).to_xml()
            elm.children = [xml_dict.xml_node(
                XS.complexType,
                children=[xml_dict.xml_node(
                    XS.group,
                    {"ref": f"ifc:{ty}"}
                )]
            )]
            return elm
        return attribute(a.name, f"ifc:{ty}", "optional").to_xml()
        
    elif isinstance(a_type, express_parser.SimpleType):
        ty = a_type.type
        simple_type_mapping = {
            'integer': 'xs:long',
            'logical': 'ifc:logical'
        }
        return attribute(a.name, simple_type_mapping[ty], "optional").to_xml()
        
    elif isinstance(a, express_parser.InverseAttribute) or \
        isinstance(a_type, express_parser.AggregationType):

        min_occurs_mult = 1
        max_occurs_mult = 1
        aggregate_type_prefix = ""

        def aggregate_type(at):
            agt = at.aggregate_type
            if at.unique:
                agt += "-unique"
            return agt
        
        if isinstance(a, express_parser.InverseAttribute):
            a_type = type('_0', (), {'type': type('_1', (), {'type': a.entity}), 'bounds': a.bounds, 'aggregate_type': a.type, 'unique': a.unique})
            is_optional = True
        else:
            if isinstance(a_type.type, express_parser.AggregationType):
                # nested lists don't require a lot of special handling, just list list
                min_occurs_mult = int(a_type.bounds.lower)
                max_occurs_mult = float("inf") if a_type.bounds.upper == "?" else int(a_type.bounds.upper)
                aggregate_type_prefix = aggregate_type(a_type) + " "
                a_type = a_type.type

        #                                            # v this should probably be enabled, but discussion pending in issue #462
                # if : # and not isinstance(mapping.flatten_type(a_type.type).type, express_parser.StringType):
        
        is_list = a_type.type.type in schema.simpletypes and not entity_configuration.get(entity.name, {}).get(a.name, {}).get('exp-attribute') == 'double-tag'
        
        is_elem = entity_configuration.get(entity.name, {}).get(a.name, {}).get('exp-attribute') == 'attribute-tag'
        
        if is_elem:

            if aggregate_type_prefix:
                # @todo when length constraint is encoded in the type how to guarantee that the correct length constraint is selected?
                attr = xml_dict.xml_node(XS.element, {'name': f'Seq-{a_type.type.type}-wrapper', 'type': f'ifc:Seq-{a_type.type.type}', 'maxOccurs': "unbounded" if a_type.bounds.upper == '?' else a_type.bounds.upper})
                # **({'minOccurs': a_type.bounds.lower} if a_type.bounds.lower != -1 else {})
                attr = xml_dict.xml_node(
                    XS.element, 
                    {'name': a.name, 'minOccurs': '0'},
                    # why:
                    # **({'minOccurs': min_occurs_mult} if min_occurs_mult != 1 else {})},
                    # 
                    # 'maxOccurs': ("unbounded" if max_occurs_mult == float("inf") else max_occurs_mult)
                    children=[xml_dict.xml_node(
                        XS.complexType,
                        children=[xml_dict.xml_node(
                            XS.sequence,
                            children=[attr]
                        )]
                    )]
                )
            else:
                attr = xml_dict.xml_node(XS.element, {'name': a.name, 'type': f'ifc:{a_type.type.type}', 'nillable': 'true', 'minOccurs': a_type.bounds.lower, 'maxOccurs': a_type.bounds.upper})
                
        elif is_list:
        
            length_constraint = []
            
            if a_type.aggregate_type == 'array':
                assert min_occurs_mult == 1
                extent = int(a_type.bounds.upper) - int(a_type.bounds.lower) + 1
                for c in (XS.minLength, XS.maxLength):
                    length_constraint += [xml_dict.xml_node(
                        c, {"value": str(extent)}
                    )]
            else:                
                if int(a_type.bounds.lower) != 1:
                    length_constraint += [xml_dict.xml_node(
                        XS.minLength,
                        {"value": (a_type.bounds.lower * min_occurs_mult)}
                    )]
                if a_type.bounds.upper != "?" and max_occurs_mult != float("inf"):
                    length_constraint += [xml_dict.xml_node(
                        XS.maxLength,
                        {"value": (a_type.bounds.upper * max_occurs_mult)}
                    )]
                    
            attr = attribute(a.name, None, "optional").to_xml()
            attr.children = [xml_dict.xml_node(
                XS.simpleType,
                
                
                children=[xml_dict.xml_node(
                    XS.restriction,
                    children=[xml_dict.xml_node(
                        XS.simpleType,
                        children=[xml_dict.xml_node(
                            XS.list,
                            {"itemType": f"ifc:{a_type.type.type}"}
                        )]
                    )] + length_constraint  
                )]
            )]
        else:        
            if a_type.type.type in schema.simpletypes:
                wrapper_postfix = "-wrapper"
            else:
                wrapper_postfix = ""
                
            ty = a_type.type.type
            assert isinstance(ty, str)
            attr = element(a.name, None, nillable="true" if is_optional else None, minOccurs="0" if is_optional else None).to_xml()
            
            min_occurs = str(min_occurs_mult * int(a_type.bounds.lower))
            if min_occurs == "1":
                min_occurs = None
                
            max_occurs = "unbounded"
            try:
                max_occurs = str(int(a_type.bounds.upper) * max_occurs_mult)
            except: pass
            
            if max_occurs == "inf":
                max_occurs = "unbounded"    
                
            array_data = [
                attribute_ref("ifc:itemType", fixed=f"ifc:{a_type.type.type}{wrapper_postfix}", use=None),
                attribute_ref("ifc:cType", fixed=aggregate_type_prefix + aggregate_type(a_type), use=None),
                attribute_ref("ifc:arraySize", use="optional")
            ]
            
            if a_type.type.type in schema.selects:
                attr.children = [xml_dict.xml_node(XS.complexType, children=[
                    xml_dict.xml_node(XS.group, {'ref': f"ifc:{a_type.type.type}", **({'minOccurs': min_occurs} if min_occurs else {}), **{'maxOccurs': max_occurs}}),
                    *(x.to_xml() for x in array_data)
                ])]
            else:
                attr.children = [complex_type([
                    element_ref(f"ifc:{a_type.type.type}{wrapper_postfix}", minOccurs=min_occurs, maxOccurs=max_occurs).to_xml()
                ], array_data
                )]
            
        return attr
    else:
        breakpoint()
        

def convert(e, name_override=None, excluded_attributes=(), restriction=None, include_inherited=False):

    subGroup = supertype = e.supertypes[0] if e.supertypes else "Entity"
    abstract_if_abstract = {"abstract": "true"} if e.abstract or (name_override and "-temp" in name_override) else {}
    
    derived = mapping.derived_in_supertype(e)
    
    def get_attributes(ent):
        e_cfg = entity_configuration.get(ent.name, {})
        keep_fwd = lambda a: e_cfg.get(a.name, {}).get('keep') != 'false' and a.name not in excluded_attributes
        keep_inv = lambda a: a.name in e_cfg
        
        inherited = []
        if include_inherited and ent.supertypes:
            inherited = get_attributes(mapping.schema.entities[ent.supertypes[0]])
        
        return inherited + list(filter(keep_fwd, ent.attributes)) + list(filter(keep_inv, ent.inverse))
    
    attributes = get_attributes(e)
    
    derived_with_additional_attributes = derived and attributes
    derived_without_additional_attributes = derived and not attributes
    
    if derived:
        yield from convert(mapping.schema.entities[e.supertypes[0]],
            name_override = e.name + ("-temp" if attributes else ""), 
            excluded_attributes = set(derived),
            restriction = e.supertypes[0],
            include_inherited = True
        ) 
        supertype = f"{e.name}-temp"
        
    if derived_without_additional_attributes:
        return

    if not name_override:
        yield element(e.name, f"ifc:{e.name}", substitutionGroup=f"ifc:{subGroup}", nillable="true", minOccurs=None, **abstract_if_abstract).to_xml()    
    
    attrs = [create_attribute(e, a) for a in attributes]
    elems = [e for e in attrs if e.tag == XS.element]
    attrs = [e for e in attrs if e.tag == XS.attribute]
    
    if elems:
        elems = [xml_dict.xml_node(
            XS.sequence,
            children=elems
        )]
    
    children = elems + attrs
    
    yield complex_type([], [], content=xml_dict.xml_node(
        XS.complexContent,
        children=[
            xml_dict.xml_node(
                XS.restriction,
                {"base": f"ifc:{restriction}"},
                children=children
            ) \
            if restriction
            else \
            xml_dict.xml_node(
                XS.extension,
                {"base": f"ifc:{supertype}"},
                children=children
            )            
        ]
    ), name=name_override or e.name, **abstract_if_abstract)


def convert_select(nm_def):
    nm, defn = nm_def
    
    def items(s=None):
        def inner(v):
            v = v.type
            if v in schema.selects:
                yield from items(schema.selects[v])
            else: yield v
        yield from itertools.chain.from_iterable(map(inner, (s or defn).values))
    
    def make_ref(s):
        if not s in schema.entities:
            s += '-wrapper'
        return f'ifc:{s}'
        
    make_elem = lambda s: xml_dict.xml_node(XS.element, {'ref': make_ref(s)})
    children = list(map(make_elem, sorted(set(items()))))
    
    yield xml_dict.xml_node(
        XS.group, 
        {'name': nm},
        children=[xml_dict.xml_node(
            XS.choice,
            children=children
        )]
    )
    
    
def convert_enum(nm_def):
    nm, defn = nm_def
    
    make_elem = lambda s: xml_dict.xml_node(XS.enumeration, {'value': s.lower()})
    children = list(map(make_elem, defn.values))
    
    yield xml_dict.xml_node(
        XS.simpleType, 
        {'name': nm},
        children=[xml_dict.xml_node(
            XS.restriction,
            {'base': 'xs:string'},
            children=children
        )]
    )
    


mapping = express_parser.parse(sys.argv[1])
schema = mapping.schema
entities = list(schema.entities.values())
selects = list(schema.selects.items())
enums = list(schema.enumerations.items())

header = complex_type(
    [
        xml_dict.xml_node(
            XS.element,
            {"name": "header", "minOccurs": "0"},
            children=[complex_type(
                [
                    element("name", "xs:string", minOccurs="0").to_xml(),
                    element("time_stamp", "xs:dateTime", minOccurs="0").to_xml(),
                    element("author", "xs:string", minOccurs="0").to_xml(),
                    element("organization", "xs:string", minOccurs="0").to_xml(),
                    element("preprocessor_version", "xs:string", minOccurs="0").to_xml(),
                    element("originating_system", "xs:string", minOccurs="0").to_xml(),
                    element("authorization", "xs:string", minOccurs="0").to_xml(),
                    element("documentation", "xs:string", minOccurs="0").to_xml(),               
                ],
                []
            )],
        )
    ],
    [
        attribute("id", "xs:ID"),
        attribute("express", "ifc:Seq-anyURI"),
        attribute("configuration", "ifc:Seq-anyURI")
    ],
    name="uos", abstract="true"
)

content = xml_dict.xml_node(
    XS.schema,
    {
        "targetNamespace": namespaces['ifc'],
        "elementFormDefault": "qualified",
        "attributeFormDefault": "unqualified"
    },
    namespaces=namespaces,
    children=[
        xml_dict.xml_node(XS.element,
            {
                "name": "uos",
                "type": "ifc:uos",
                "abstract": "true"
            },
        ),
        xml_dict.xml_node(XS.simpleType,
            {
                "name": "Seq-anyURI",
            },
            children=[
                xml_dict.xml_node(XS.list,
                    {
                        "itemType": "xs:anyURI",
                    }
                )
            ]
        ),
        header,
        element("ifcXML", "ifc:ifcXML", minOccurs=None, substitutionGroup="ifc:uos").to_xml(),
        complex_type([], [], content=xml_dict.xml_node(
            XS.complexContent,
            children=[xml_dict.xml_node(
                XS.extension,
                {"base": "ifc:uos"},
                children = [xml_dict.xml_node(
                    XS.choice,
                    {"minOccurs": "0", "maxOccurs": "unbounded"},
                    children=[(
                        xml_dict.xml_node(XS.element, {"ref": "ifc:Entity"})
                    )]
                )]
            
            )]
        ),name="ifcXML")
    ] + list(flatmap(convert, entities)) + \
        list(flatmap(convert_select, selects)) + \
        list(flatmap(convert_enum, enums))
)

xml_dict.serialize([content], sys.argv[2])
