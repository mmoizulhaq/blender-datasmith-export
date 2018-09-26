import struct
from xml.etree import ElementTree
import os
from os import path
import itertools
import bpy
from functools import reduce

import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def read_array_data(io, data_struct):
	struct_size = struct.calcsize(data_struct)
	data_struct = "<" + data_struct # force little endianness

	count = struct.unpack("<I", io.read(4))[0]
	data = io.read(count * struct_size)
	unpacked_data = list(struct.iter_unpack(data_struct, data))
	return [tup[0] if len(tup) == 1 else tup for tup in unpacked_data ]


def flatten(it):
	data = []
	for d in it:
		if isinstance(d, float) or isinstance(d, int):
			data.append(d)
		else:
			data += [*d]
	return data

def write_array_data(io, data_struct, data):
	# first get data length
	length = len(data)
	data_struct = '<I' + (data_struct) * length
	flat_data = flatten(data)
	print(flat_data)
	output = struct.pack(data_struct, length, *flat_data)
	io.write(output)

def read_data(io, data_struct):
	struct_size = struct.calcsize(data_struct)
	data_struct = "<" + data_struct	# force little endianness
	data = io.read(struct_size)
	unpacked_data = struct.unpack(data_struct, data)
	return unpacked_data

def read_string(io):
	count = struct.unpack("<I", io.read(4))[0]
	data = io.read(count)
	return data.decode('utf-8').strip('\0')


def write_null(io, num_bytes):
	io.write(b'\0' * num_bytes)

def write_string(io, string):
	string_bytes = string.encode('utf-8') + b'\0'
	length = len(string_bytes)
	io.write(struct.pack('<I', length))
	io.write(string_bytes)

def sanitize_name(name):
	return name.replace('.', '_')

class UDElement:
	"""convenience for all elements in the udatasmith file"""
	node_type = 'Element'
	node_group = None

	class UDElementException(Exception):
		pass

	@classmethod
	def new(cls, name, parent=None, **kwargs):
		if parent is None:
			raise UDElementException('Tried to create an element without a parent.')
		if cls.node_group is None:
			raise UDElementException("%s doesn't override `node_group`, without it, parent registration won't work.")
		
		group = getattr(parent, cls.node_group, {})

		name = sanitize_name(name)

		elem = group.get(name)
		if elem:
			return elem
			
		new_object = cls(parent=parent, name=name, **kwargs)
		
		if not new_object.name:
			raise UDElementException("object created without name")

		group = getattr(parent, cls.node_group, {})
		group[new_object.name] = new_object
		setattr(parent, cls.node_group, group)

		return new_object


	def render(self, parent):
		elem = ElementTree.SubElement(parent, self.node_type)
		elem.attrib['name'] = self.name
		return elem

	def __repr__(self):
		return '{}: {}'.format(type(self).__name__, self.name)


class UDMesh(UDElement):
	node_type = 'StaticMesh'
	node_group = 'meshes'

	def __init__(self, path=None, node:ElementTree.Element = None, parent = None, name=None):
		self.parent = parent
		self.name = name
		if node:
			self.init_with_xmlnode(node)
		elif path:
			self.init_with_path(path)
		
		else:
			self.init_fields()

		self.check_fields() # to test if it is possible for these fields to have different values

	def init_fields(self):
		self.source_models = 'SourceModels'
		self.struct_property = 'StructProperty'
		self.datasmith_mesh_source_model = 'DatasmithMeshSourceModel'

		self.materials = {}

		self.tris_material_slot = []
		self.tris_smoothing_group = []
		self.vertices = []
		self.triangles = []
		self.vertex_normals = []
		self.uvs = []
		self.relative_path = None
		self.hash = ''


	def check_fields(self):
		assert self.name != None
		assert self.source_models == 'SourceModels'
		assert self.struct_property == 'StructProperty'
		assert self.datasmith_mesh_source_model == 'DatasmithMeshSourceModel'

	def init_with_xmlnode(self, node:ElementTree.Element):
		self.name = node.attrib['name']
		self.label = node.attrib['label']
		self.relative_path = node.find('file').attrib['path']
		
		parent_path = path.dirname(os.path.abspath(self.parent.path))
		self.init_with_path(path.join(parent_path, self.relative_path))
		# self.materials = {n.attrib['id']: n.attrib['name'] for n in node.iter('Material')}

		# flatten material lists
		material_map = {int(n.attrib['id']): idx for idx, n in enumerate(node.iter('Material'))}
		self.materials = {idx: n.attrib['name'] for idx, n in enumerate(node.iter('Material'))}
		if 0 not in material_map:
			last_index = len(material_map)
			material_map[0] = last_index
			self.materials[last_index] = 'default_material'

		print(material_map)
		try:
			self.tris_material_slot = list(map(lambda x: material_map[x], self.tris_material_slot))
		except Exception:
			print(self.tris_material_slot)


	def init_with_path(self, path):
		with open(path, 'rb') as file:

			self.a01 = read_data(file, 'II') # 8 bytes
			self.name = read_string(file)

			self.a02 = file.read(5)
			
			self.source_models = read_string(file)
			self.struct_property = read_string(file)
			self.a03 = file.read(8)

			self.datasmith_mesh_source_model = read_string(file)
			
			self.a04 = file.read(49)

			self.tris_material_slot = read_array_data(file, "I")
			self.tris_smoothing_group = read_array_data(file, "I")
			
			self.vertices = read_array_data(file, "fff")
			self.triangles = read_array_data(file, "I")
			
			self.a05 = read_array_data(file, "I") # 4 bytes, not sure about this structure
			self.a06 = read_array_data(file, "I") # 4 bytes, not sure about this structure

			self.vertex_normals = read_array_data(file, "fff")
			self.uvs = read_array_data(file, "ff")
			
			self.a07 = file.read(36) # hmmm
			
			self.checksum = file.read(16) # I guess... seems to be non deterministic
			
			self.a08 = file.read() #4 bytes more
			
			# small check here to crash if something is suspicious
			assert len(self.triangles) == len(self.uvs)
			assert len(self.vertex_normals) == len(self.uvs)
			assert self.a08 == b'\x00\x00\x00\x00' # just to be sure its the end
		
	def write_to_path(self, path):
		with open(path, 'wb') as file:
			#write_null(file, 8)
			file.write(b'\x01\x00\x00\x00\xfd\x04\x00\x00')
			write_string(file, self.name)
			#write_null(file, 5)
			file.write(b'\x00\x01\x00\x00\x00')
			write_string(file, self.source_models)
			write_string(file, self.struct_property)
			write_null(file, 8)

			write_string(file, self.datasmith_mesh_source_model)
			
			#write_null(file, 49)\
			file.write(
				b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
				b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x6c\x04\x00\x00\x6c\x04\x00'
				b'\x00\x7d\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00')

			# further analysis revealed:
			# this loops are per triangle
			write_array_data(file, 'I', self.tris_material_slot)
			write_array_data(file, 'I', self.tris_smoothing_group)
			# per vertex
			write_array_data(file, 'fff', self.vertices)
			# per vertexloop
			write_array_data(file, 'I', self.triangles)
			write_null(file, 8)
			write_array_data(file, 'fff', self.vertex_normals)
			write_array_data(file, 'ff', self.uvs)
			write_null(file, 36)
			write_null(file, 16)
			write_null(file, 4)

	def render(self, parent):
		elem = super().render(parent=parent)
		elem.attrib['label'] = self.name
		for idx, m in enumerate(self.materials):
			ElementTree.SubElement(elem, 'Material', id=str(idx), name=sanitize_name(m))
		if self.relative_path:
			path = self.relative_path.replace('\\', '/')
			ElementTree.SubElement(elem, 'file', path=path)
		lm_uv = ElementTree.SubElement(elem, 'LightmapUV', value='-1')
		ElementTree.SubElement(elem, 'Hash', value=self.hash)
		return elem

	def save(self, basedir, folder_name):
		self.relative_path = path.join(folder_name, self.name + '.udsmesh')
		abs_path = path.join(basedir, self.relative_path)
		self.write_to_path(abs_path)
		
		import hashlib
		hash_md5 = hashlib.md5()
		with open(abs_path, "rb") as f:
			for chunk in iter(lambda: f.read(4096), b""):
				hash_md5.update(chunk)
		self.hash = hash_md5.hexdigest()



class UDMaterial(UDElement):
	node_type = 'Material'
	node_group = 'materials'

	def __init__(self, name: str, node=None, parent=None, **kwargs):
		self.name = name # this is like the primary identifier
		if node:
			self.label = node.attrib['label']
		# datasmith file has a subnode 'shader' with some for now irrelevant info

class UDMasterMaterial(UDMaterial):
	class Prop:
		prop_type = None
		def render(self, parent, name):
			return ElementTree.SubElement(parent, 'KeyValueProperty', name=name, type=self.prop_type, val=repr(self))
	class PropColor(Prop):
		prop_type = 'Color'
		def __init__(self, r=0.0, g=0.0, b=0.0, a=1.0):
			self.r, self.g, self.b, self.a = r, g, b, a
		def __repr__(self):
			return '(R={:6f},G={:6f},B={:6f},A={:6f})'.format(self.r, self.g, self.b, self.a)
	class PropBool(Prop):
		prop_type = 'Bool'
		def __init__(self, b):
			self.b = b
		def __repr__(self):
			return 'true' if self.b else 'false'

	'''sketchup datasmith outputs Master material, it may be different'''
	''' has params Type and Quality'''
	node_type = 'MasterMaterial'
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.properties = {}

	def render(self, parent):
		elem = super().render(parent)
		elem.attrib['Type'] = '1'
		elem.attrib['Quality'] = '0'
		elem.attrib['label'] = self.name
		for name, prop in self.properties.items():
			prop.render(name=name, parent=elem)

class UDTexture(UDElement):
	node_type = 'Texture'
	node_group = 'textures'

	def render(self, parent):
		elem = super().render(parent)
		elem.attrib['file'] = 'path/to/file'
		h = ElementTree.SubElement(elem, 'Hash', value="file md5 hash")
	def save(self, basepath):
		log.debug('saving tex {} to {}'.format(self, basepath))

class UDActor(UDElement):

	node_type = 'Actor'
	node_group = 'objects'

	class Transform:
		def __init__(self, tx=0, ty=0, tz=0, 
					 qw=0, qx=0, qy=0, qz=0,
					 sx=0, sy=0, sz=0, qhex = None):
			self.loc = (float(tx), float(ty), float(tz))
			self.rot = (float(qw), float(qx), float(qy), float(qz))
			self.scale = (float(sx), float(sy), float(sz))
			# don't know what qhex is
		def render(self, parent):
			f = lambda n: "{:.6f}".format(n)
			tx, ty, tz = self.loc
			qw, qx, qy, qz = self.rot
			sx, sy, sz = self.scale
			return ElementTree.SubElement(parent, 'Transform',
					tx=f(tx), ty=f(ty), tz=f(tz), 
					qw=f(qw), qx=f(qx), qy=f(qy), qz=f(qz),
					sx=f(sx), sy=f(sy), sz=f(sz),
				)



	def __init__(self, *, parent, node=None, name=None, layer='Layer0'):
		self.transform = UDActor.Transform()
		self.objects = {}
		self.name = name
		self.layer = layer
		if node:
			self.name = node.attrib['name']
			self.layer = node.attrib['layer']
			node_transform = node.find('Transform')
			if node_transform is not None:
				self.transform = UDActor.Transform(**node_transform.attrib)
			else:
				import pdb; pdb.set_trace()
			node_children = node.find('children')
			if node_children:
				for child in node_children:
					if child.tag == "Actor":
						UDActor(node=child, parent=self)
					if child.tag == "ActorMesh":
						UDActorMesh(node=child, parent=self)

	def render(self, parent):
		elem = super().render(parent)
		elem.attrib['layer'] = self.layer
		self.transform.render(elem)

		if len(self.objects) > 0:
			children = ElementTree.SubElement(elem, 'children')
			for name, child in self.objects.items():
				child.render(children)

		return elem


class UDActorMesh(UDActor):

	node_type = 'ActorMesh'

	def __init__(self, *, parent, node=None, name=None):
		super().__init__(parent=parent, node=node, name=name)
		if node:
			self.mesh = node.find('mesh').attrib['name']
			self.materials = {n.attrib['id']: n.attrib['name'] for n in node.findall('material')}

	def render(self, parent):
		elem = super().render(parent)
		mesh = ElementTree.SubElement(elem, 'mesh')
		mesh.attrib['name'] = sanitize_name(self.mesh)
		

class UDActorLight(UDActor):

	node_type = 'Light'

	LIGHT_POINT = 'PointLight'
	LIGHT_SPOT = 'SpotLight'

	LIGHT_UNIT_CANDELAS = 'Candelas'

	def __init__(self, *, parent, node=None, name=None, light_type = LIGHT_POINT, color = (1.0,1.0,1.0)):
		super().__init__(parent=parent, node=node, name=name)
		self.type = light_type
		self.intensity = 1500
		self.intensity_units = UDActorLight.LIGHT_UNIT_CANDELAS
		self.color = color
		self.inner_cone_angle = 22.5
		self.outer_cone_angle = 25
		self.post = []
		if node:
			self.parse(node)
	def parse(self, node):
		self.type = node.attrib['type']

		# self.intensity =       	node.find('Intensity').attrib['value']
		# self.intensity_units = 	node.find('IntensityUnits').attrib['value']
		# self.color =           	node.find('Color').attrib['value']
		# self.inner_cone_angle =	node.find('InnerConeAngle').attrib['value']
		# self.outer_cone_angle =	node.find('OuterConeAngle').attrib['value']

	def render(self, parent):
		elem = super().render(parent)
		elem.attrib['type'] = self.type
		elem.attrib['enabled'] = '1'
		ElementTree.SubElement(elem, 'Intensity',     	value='{:6f}'.format(self.intensity))
		ElementTree.SubElement(elem, 'IntensityUnits',	value=self.intensity_units)
		f= '{:6f}'
		ElementTree.SubElement(	elem, 'Color', usetemp='0', temperature='6500.0',
		                       	R=f.format(self.color[0]),
		                       	G=f.format(self.color[1]),
		                       	B=f.format(self.color[2]),
		)
		if self.type == UDActorLight.LIGHT_SPOT:
			ElementTree.SubElement(elem, 'InnerConeAngle',	value='{:6f}'.format(self.inner_cone_angle))
			ElementTree.SubElement(elem, 'OuterConeAngle',	value='{:6f}'.format(self.outer_cone_angle))
		return elem


class UDActorCamera(UDActor):

	node_type = 'Camera'

	def __init__(self, *, parent, node=None, name=None):
		super().__init__(parent=parent, node=node, name=name)
		self.sensor_width = 36.0
		self.sensor_aspect_ratio = 1.777778
		self.focus_distance = 1000.0
		self.f_stop = 5.6
		self.focal_length = 32.0
		self.post = []
		if node:
			self.parse(node)

	def parse(self, node):
		self.sensor_width =       	node.find('SensorWidth').attrib['value']
		self.sensor_aspect_ratio =	node.find('SensorAspectRatio').attrib['value']
		self.focus_distance =     	node.find('FocusDistance').attrib['value']
		self.f_stop =             	node.find('FStop').attrib['value']
		self.focal_length =       	node.find('FocalLength').attrib['value']

	def render(self, parent):
		elem = super().render(parent)
		ElementTree.SubElement(elem, 'SensorWidth',      	value='{:6f}'.format(self.sensor_width))
		ElementTree.SubElement(elem, 'SensorAspectRatio',	value='{:6f}'.format(self.sensor_aspect_ratio))
		ElementTree.SubElement(elem, 'FocusDistance',    	value='{:6f}'.format(self.focus_distance))
		ElementTree.SubElement(elem, 'FStop',            	value='{:6f}'.format(self.f_stop))
		ElementTree.SubElement(elem, 'FocalLength',      	value='{:6f}'.format(self.focal_length))
		ElementTree.SubElement(elem, 'Post')
		return elem




class UDScene(UDElement):

	node_type = 'DatasmithUnrealScene'

	def __init__(self, source=None):
		self.init_fields()
		if type(source) is str:
			self.path = source
			self.init_with_path(self.path)

		self.check_fields() # to test if it is possible for these fields to have different values

	def init_fields(self):
		self.name = 'udscene_name'

		self.materials = {}
		self.meshes = {}
		self.objects = {}
		self.textures = {}

	def check_fields(self):
		pass

	def init_with_path(self, path):

		tree = ElementTree.parse(path)
		root = tree.getroot()

		self.version = root.find('Version').text
		self.sdk_version = root.find('SDKVersion').text
		self.host = root.find('Host').text
		# there are other bunch of data that i'll skip for now

		classes = [
			UDMaterial,
			UDMasterMaterial,
			UDMesh,
			UDActor,
			UDActorMesh,
			UDActorCamera,
			UDActorLight,
		]

		mappings = {cls.node_type:cls for cls in classes} 

		for node in root:
			name = node.get('name') # most relevant nodes have a name as identifier
			cls = mappings.get(node.tag)
			if cls:
				cls.new(parent=self, name=name, node=node)

	def render(self):
		tree = ElementTree.Element('DatasmithUnrealScene')

		version = ElementTree.SubElement(tree, 'Version')
		version.text = '0.20' # to get from context?

		sdk = ElementTree.SubElement(tree, 'SDKVersion')
		sdk.text = '4.20E1' # to get from context?

		host = ElementTree.SubElement(tree, 'Host')
		host.text = 'Blender'

		application = ElementTree.SubElement(tree, 'Application', Vendor='Blender', ProductName='Blender', ProductVersion='2.80')
		user = ElementTree.SubElement(tree, 'User', ID='00000000000000000000000000000000', OS='Windows 8.1')

		for name, obj in self.objects.items():
			obj.render(tree)
		for name, mesh in self.meshes.items():
			mesh.render(tree)
		for name, mat in self.materials.items():
			mat.render(tree)
		for name, tex in self.textures.items():
			tex.render(tree)

		return tree

	def save(self, basedir, name):
		self.name = name

		folder_name = name + '_Assets'
		# make sure basepath_Assets directory exists
		try:
			os.makedirs(path.join(basedir, folder_name))
		except FileExistsError as e:
			pass

		for _name, mesh in self.meshes.items():
			mesh.save(basedir, folder_name)
		for _name, tex in self.textures.items():
			tex.save(basedir, folder_name)
		
		tree = self.render()
		txt = ElementTree.tostring(tree)
		from xml.dom import minidom
		pretty_xml = minidom.parseString(txt).toprettyxml()

		filename = path.join(basedir, self.name + '.udatasmith')

		with open(filename, 'w') as f:
			f.write(pretty_xml)
	