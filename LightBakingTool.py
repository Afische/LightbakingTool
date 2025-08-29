import maya.app.renderSetup.model.override as override
import maya.app.renderSetup.model.selector as selector
import maya.app.renderSetup.model.collection as collectionTool
import maya.app.renderSetup.model.renderLayer as renderLayer
import maya.app.renderSetup.model.renderSetup as renderSetup
import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui
import comtypes.client
import sys
import ast
import re
import os
import time
import string
import platform
import subprocess
import SharedUtils
from wand.image import Image
from collections import OrderedDict
from functools import partial
from six.moves import reload_module
reload_module(SharedUtils)

maya_version = cmds.about(apiVersion=True)

if maya_version >= 20260000:  # Maya 2026+
	try:
		from PySide6.QtCore import *
		from PySide6.QtGui import *
		from PySide6.QtWidgets import *
		from shiboken6 import wrapInstance
	except ImportError:
		cmds.warning("PySide6 import failed for Maya 2026+")
elif maya_version >= 20170000:  # Maya 2017-2025
	try:
		from PySide2.QtCore import *
		from PySide2.QtGui import *
		from PySide2.QtWidgets import *
		from shiboken2 import wrapInstance
	except ImportError:
		cmds.warning("PySide2 import failed for Maya 2017-2025")
else:  # Maya < 2017
	try:
		from PySide.QtCore import *
		from PySide.QtGui import *
		from shiboken import wrapInstance
	except ImportError:
		cmds.warning("PySide import failed for Maya < 2017")

def getMayaWindow():
	'''
	Utility function to get pointer to Maya's main UI parent window
	Returns: Pointer, points to Maya's main UI parent window as a QWidget object
	'''
	pointer = omui.MQtUtil.mainWindow()
	if pointer != None:
		return wrapInstance(int(pointer), QWidget)

'''
Global variables
'''
GB_STYLE = "QGroupBox { padding: 10px; border: 1px solid grey;}"
MISSING_OBJ_COL = 'missingObjectsCollection'
TEMP_COL = 'TempCollection'

class LightBakingTool(QDialog):
	def __init__(self, parent=getMayaWindow()):
		self.renderSetsName = 'renderSets'
		self.renderSetsDict = {}
		self.currentRenderset = ''
		self.projectDirectory = cmds.workspace(q=True, rd=True)
		self.mayaVersion = int(cmds.about(v=True))
		self.ignoreProjects = ['potter']
		self.verticalSpacer = QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.useMentalRay = False
		self.renderType = 'Arnold'

		cmds.optionVar(iv=("renderSetup_includeAllLights", False))

		super(LightBakingTool, self).__init__(parent)

		# ------------------------------
		# Main Window Initialization.
		# ------------------------------
		self.parent = parent
		self.setWindowFlags(Qt.Dialog)
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.mainWindowName = 'LightBakingToolMainWindowObject'

		# Delete window if it already exists
		if cmds.window(self.mainWindowName, exists=True):
			cmds.deleteUI(self.mainWindowName)

		# Dialog window settings
		self.setObjectName(self.mainWindowName)
		self.setWindowTitle('Environment Lighting Bake Tool')

		self.mainLayout = QVBoxLayout()
		self.mainLayout.setContentsMargins(5, 5, 5, 5)
		self.setLayout(self.mainLayout)

		self.gridLayout = QGridLayout()
		self.gridLayout.setColumnStretch(1, 2)
		self.mainLayout.addLayout(SharedUtils.UniversalHelpMenu(self,
			helpPageUrl='https://socialgamingnetwork.jira.com/wiki/spaces/SFOPS/pages/2312208387/Light+Baking+Tool'))
		self.renderTypeLable = QLabel('Rendering Using {}'.format(self.renderType))
		self.renderTypeLable.setFont(QFont('Arial', 12, weight=QFont.Bold))
		self.mainLayout.addWidget(self.renderTypeLable)
		self.mainLayout.addLayout(self.gridLayout)
		# ------------------------------
		# RenderSets Ui Setup.
		# ------------------------------
		self.renderSetsGroupBox = QGroupBox('Render Sets:')
		self.renderSetsGroupBox.setStyleSheet(GB_STYLE)
		self.renderSetsGroupBoxLayout = QVBoxLayout()
		self.renderSetsGroupBox.setLayout(self.renderSetsGroupBoxLayout)

		self.pngNameReminderLabel = QLabel('Note: Render Set name = Combined PNG name.')

		self.renderSetDivider = QFrame()
		self.renderSetDivider.setFrameShape(QFrame().HLine)
		self.renderSetDivider.setFrameShadow(QFrame().Sunken)

		self.renderSetsListWidget = QListWidget()
		self.renderSetsListWidget.setLineWidth(0)
		self.renderSetsListWidget.setSortingEnabled(True)
		self.renderSetsListWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
		# Add right click options for self.renderSetsListWidget
		self.renderSetsListWidget.setContextMenuPolicy(Qt.CustomContextMenu)
		#self.renderSetsListWidget.connect(self.renderSetsListWidget, SIGNAL('customContextMenuRequested(QPoint)' ), self.RenderSetsListContextMenu)
		self.renderSetsListWidget.customContextMenuRequested.connect(self.RenderSetsListContextMenu)

		self.renderSetsNewButton = QPushButton('New')
		self.renderSetsDeleteButton = QPushButton('Delete')
		self.renderSetsRenameButton = QPushButton('Rename')
		self.toggleRenderableButton = QPushButton('Toggle All Renderable')
		self.renderSetsSortButton = QPushButton('Sort')
		self.uvSetRefreshButton = QPushButton('Refresh All Objects uvSets')
		self.validateRenderSetsButton = QPushButton('Validate Render Sets!')
		self.autoPopulateSetsButton = QPushButton('Auto Populate Based On Selected RM_')

		self.renderSetsGroupBoxLayout.addWidget(self.pngNameReminderLabel)
		self.renderSetsGroupBoxLayout.addWidget(self.renderSetDivider)
		self.renderSetsGroupBoxLayout.addWidget(self.renderSetsListWidget)
		self.renderSetsGroupBoxLayout.addWidget(self.renderSetsNewButton)
		self.renderSetsGroupBoxLayout.addWidget(self.renderSetsDeleteButton)
		self.renderSetsGroupBoxLayout.addWidget(self.renderSetsRenameButton)
		self.renderSetsGroupBoxLayout.addWidget(self.toggleRenderableButton)
		#self.renderSetsGroupBoxLayout.addWidget(self.renderSetsSortButton)
		self.renderSetsGroupBoxLayout.addWidget(self.uvSetRefreshButton)
		self.renderSetsGroupBoxLayout.addWidget(self.validateRenderSetsButton)

		if not any(x in self.projectDirectory.lower() for x in self.ignoreProjects):
			self.renderSetsGroupBoxLayout.addWidget(self.autoPopulateSetsButton)

		# ------------------------------
		# Objects Ui Setup.
		# ------------------------------
		self.rightGridLayout = QGridLayout()
		self.rightGridLayout.setColumnStretch(1, 2)

		self.objectsGroupBox = QGroupBox('Objects:')
		self.objectsGroupBox.setMinimumWidth(350)
		self.objectsGroupBoxLayout = QVBoxLayout()
		self.objectsGroupBox.setLayout(self.objectsGroupBoxLayout)

		self.objectsGroupTreeWidget = QTreeWidget()
		self.objectsGroupTreeWidget.setHeaderLabels(['Mesh', 'uvSet'])
		self.objectsGroupTreeWidget.setColumnWidth(0, 255)
		self.objectsGroupTreeWidget.setColumnWidth(1, 45)
		self.objectsGroupTreeWidget.setLineWidth(0)
		self.objectsGroupTreeWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)

		self.uvSetLayout = QHBoxLayout()
		self.uvSetLabel = QLabel('uvSet:')
		self.uvSetLabel.setAlignment(Qt.AlignRight)
		self.uvSetComboBox = QComboBox()
		self.uvSets = ['map1', 'uvSet', 'uvSet1']
		self.uvSetComboBox.addItems(self.uvSets)
		self.uvSetComboBox.setCurrentIndex(1)

		self.uvSetLayout.addWidget(self.uvSetLabel)
		self.uvSetLayout.addWidget(self.uvSetComboBox)

		self.objectsGroupLoadButton = QPushButton('Add Meshes')
		self.objectsGroupRemoveButton = QPushButton('Remove Meshes')
		self.objectsGroupSelectButton = QPushButton('Select Meshes')

		self.objectsGroupBoxLayout.addWidget(self.objectsGroupTreeWidget)
		self.objectsGroupBoxLayout.addLayout(self.uvSetLayout)
		self.objectsGroupBoxLayout.addWidget(self.objectsGroupLoadButton)
		self.objectsGroupBoxLayout.addWidget(self.objectsGroupRemoveButton)
		self.objectsGroupBoxLayout.addWidget(self.objectsGroupSelectButton)

		# ------------------------------
		# RenderLayers Ui Setup.
		# ------------------------------
		self.renLayerGroupBox = QGroupBox('Render Layers:')
		self.renLayerGroupBox.setMinimumWidth(350)
		self.renLayerGroupBoxLayout = QVBoxLayout()
		self.renLayerGroupBox.setLayout(self.renLayerGroupBoxLayout)

		self.renLayerTreeWidget = QTreeWidget()
		self.renLayerTreeWidget.setHeaderLabels(['Render Layer', 'Blending'])
		self.renLayerTreeWidget.setColumnWidth(0, 220)
		self.renLayerTreeWidget.setColumnWidth(1, 40)
		self.renLayerTreeWidget.setLineWidth(0)
		self.renLayerTreeWidget.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.layerBlendingLayout = QHBoxLayout()
		self.layerBlendingLabel = QLabel('Layer Blending Type:')
		self.layerBlendingLabel.setAlignment(Qt.AlignRight)

		self.layerBlendingComboBox = QComboBox()
		self.blendTypes = ['Additive', 'Multiply']
		self.layerBlendingComboBox.addItems(self.blendTypes)

		self.layerBlendingLayout.addWidget(self.layerBlendingLabel)
		self.layerBlendingLayout.addWidget(self.layerBlendingComboBox)

		self.renLayerAddSelectedButton = QPushButton('Add Selected Render Layer')
		self.renLayerAddSelectedToAllButton = QPushButton('Add Selected Render Layer to All Sets')
		self.renLayerAddButton = QPushButton('Load Render Layers')
		self.renLayerRemoveButton = QPushButton('Remove Layer')
		self.renLayerPopulateAllButton = QPushButton('Populate All RenderSets')

		self.moveItemsRenLayerLayout = QHBoxLayout()
		self.upRenLayerButton = QPushButton('MOVE UP')
		self.downRenLayerButton = QPushButton('MOVE DOWN')
		self.moveItemsRenLayerLayout.addWidget(self.upRenLayerButton)
		self.moveItemsRenLayerLayout.addWidget(self.downRenLayerButton)

		self.renLayerGroupBoxLayout.addWidget(self.renLayerTreeWidget)
		self.renLayerGroupBoxLayout.addLayout(self.layerBlendingLayout)
		self.renLayerGroupBoxLayout.addWidget(self.renLayerAddSelectedButton)
		self.renLayerGroupBoxLayout.addWidget(self.renLayerAddSelectedToAllButton)
		self.renLayerGroupBoxLayout.addWidget(self.renLayerAddButton)
		self.renLayerGroupBoxLayout.addWidget(self.renLayerRemoveButton)
		self.renLayerGroupBoxLayout.addWidget(self.renLayerPopulateAllButton)
		self.renLayerGroupBoxLayout.addLayout(self.moveItemsRenLayerLayout)

		# ------------------------------
		# 3rd column UI Setup.
		# ------------------------------
		self.columnThreeLayout = QVBoxLayout()

		# ------------------------------
		# Resolution QComboBox Setup.
		# ------------------------------
		self.resLayout = QHBoxLayout()
		self.resLabel = QLabel('Resolution:')
		self.resLabel.setAlignment(Qt.AlignRight)

		self.resComboBox = QComboBox()
		texSize = ['64', '128', '256', '512', '1024', '2048']
		self.resComboBox.addItems(texSize)
		self.resComboBox.setCurrentIndex(4)

		self.resLayout.addWidget(self.resLabel)
		self.resLayout.addWidget(self.resComboBox)

		# ------------------------------
		# Color Mode QComboBox Setup.
		# ------------------------------
		self.modeLayout = QHBoxLayout()
		self.modeLabel = QLabel('Color Mode:')
		self.modeLabel.setAlignment(Qt.AlignRight)

		self.modeComboBox = QComboBox()
		colorModes = ['Light and Color', 'Only Light', 'Only Global Illumination', 'Occlusion']
		self.modeComboBox.addItems(colorModes)
		self.modeComboBox.setCurrentIndex(0)
		# dissable color mode if not useMentalRay
		if not self.useMentalRay:
			self.modeLabel.setEnabled(False)
			self.modeComboBox.setEnabled(False)

		self.modeLayout.addWidget(self.modeLabel)
		self.modeLayout.addWidget(self.modeComboBox)

		# ------------------------------
		# Fill Texture Seams QDoubleSpinBox Setup.
		# ------------------------------
		self.fillSeamsLayout = QHBoxLayout()
		self.fillSeamsLabel = QLabel('Fill Texture Seams:')
		self.fillSeamsLabel.setAlignment(Qt.AlignRight)

		self.fillSeamsSlider = QDoubleSpinBox()
		self.fillSeamsSlider.setMinimum(0)
		self.fillSeamsSlider.setMaximum(10)
		self.fillSeamsSlider.setValue(3)
		self.fillSeamsSlider.setSingleStep(0.01)

		self.fillSeamsLayout.addWidget(self.fillSeamsLabel)
		self.fillSeamsLayout.addWidget(self.fillSeamsSlider)

		# ------------------------------
		# Light Map Prefix QLineEdit Setup.
		# ------------------------------
		self.addPrefixLayout = QHBoxLayout()
		self.addPrefixLabel = QLabel('Light Map Prefix:')
		self.addPrefixLabel.setAlignment(Qt.AlignRight)

		self.addPrefixLineEdit = QLineEdit("BAKE")

		self.addPrefixLayout.addWidget(self.addPrefixLabel)
		self.addPrefixLayout.addWidget(self.addPrefixLineEdit)

		# ------------------------------
		# Auto layout lightmap uvs, Arnold Only.
		# ------------------------------
		if not self.useMentalRay:
			self.autoLayoutLightmapUVs = QCheckBox('Auto Layout Lightmap UVs')
		# ------------------------------
		# Divider Setup.
		# ------------------------------
		self.bottomLine = QFrame()
		self.bottomLine.setFrameShape(QFrame().HLine)
		self.bottomLine.setFrameShadow(QFrame().Sunken)

		# ------------------------------
		# Photoshop Options Setup.
		# ------------------------------
		self.formatLayout = QHBoxLayout()
		self.formatLabel = QLabel('Format:')
		self.formatLabel.setAlignment(Qt.AlignRight)

		self.formatComboBox = QComboBox()
		imgFormat = ['PNG']
		self.formatComboBox.addItems(imgFormat)

		self.formatLayout.addWidget(self.formatLabel)
		self.formatLayout.addWidget(self.formatComboBox)

		self.psdCreationGroupBox = QGroupBox('PSD File Creation:')
		self.psdCreationGroupBoxLayout = QVBoxLayout()
		self.psdCreationGroupBox.setLayout(self.psdCreationGroupBoxLayout)

		self.createPsdLabel = QLabel('Create a Layered PSD file for each Render Set.\n'
										   'Each Render Layer will be a layer in the PSD file.')
		self.createPsdLabel.setAlignment(Qt.AlignLeft)
		self.createPSDtCheckbox = QCheckBox('Create PSD')
		self.createPSDtCheckbox.setChecked(True)
		self.combineImgCheckbox = QCheckBox('Combine to PNG')
		self.combineImgNoteLabel = QLabel('Note: Leave Prefix/Suffix Blank if your RenderSet\nnames already include them!')
		self.combineImgNoteLabel.setEnabled(False)
		# Add Prefix to all png Setup. #
		self.combineImgPrefixLayout = QHBoxLayout()
		self.combineImgPrefixLabel = QLabel('PNG Prefix:')
		self.combineImgPrefixLabel.setAlignment(Qt.AlignRight)
		self.combineImgPrefixLabel.setEnabled(False)

		self.combineImgPrefixLineEdit = QLineEdit()
		self.combineImgPrefixLineEdit.setEnabled(False)

		self.combineImgPrefixLayout.addWidget(self.combineImgPrefixLabel)
		self.combineImgPrefixLayout.addWidget(self.combineImgPrefixLineEdit)
		# Add Suffix to all png Setup. #
		self.combineImgSuffixLayout = QHBoxLayout()
		self.combineImgSuffixLabel = QLabel('PNG Suffix:')
		self.combineImgSuffixLabel.setAlignment(Qt.AlignRight)
		self.combineImgSuffixLabel.setEnabled(False)

		self.combineImgSuffixLineEdit = QLineEdit()
		self.combineImgSuffixLineEdit.setEnabled(False)

		self.combineImgSuffixLayout.addWidget(self.combineImgSuffixLabel)
		self.combineImgSuffixLayout.addWidget(self.combineImgSuffixLineEdit)

		self.hookUpLMTexturesCheckbox = QCheckBox('Hook Up Lightmap Textures')
		self.hookUpLMTexturesCheckbox.setDisabled(True)
		self.createUvSnapshotsCheckbox = QCheckBox('Create UV uvSnapshots')
		self.doItAllCheckbox = QCheckBox('Just do it all!(Non Verbose)')
		self.doItAllCheckbox.setChecked(True)
		self.resForTypeLayout = QVBoxLayout()

		self.columnThreeSpacer03 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.columnThreeSpacer04 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.columnThreeSpacer05 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.columnThreeSpacer06 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.columnThreeSpacer07 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)
		self.columnThreeSpacer08 = QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Minimum)

		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer05)
		self.psdCreationGroupBoxLayout.addWidget(self.createPsdLabel)
		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer06)
		self.psdCreationGroupBoxLayout.addWidget(self.createPSDtCheckbox)
		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer03)
		self.psdCreationGroupBoxLayout.addWidget(self.combineImgCheckbox)
		self.psdCreationGroupBoxLayout.addWidget(self.combineImgNoteLabel)
		self.psdCreationGroupBoxLayout.addLayout(self.combineImgPrefixLayout)
		self.psdCreationGroupBoxLayout.addLayout(self.combineImgSuffixLayout)
		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer07)
		self.psdCreationGroupBoxLayout.addWidget(self.hookUpLMTexturesCheckbox)
		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer04)
		self.psdCreationGroupBoxLayout.addWidget(self.createUvSnapshotsCheckbox)
		self.psdCreationGroupBoxLayout.addItem(self.columnThreeSpacer08)
		self.psdCreationGroupBoxLayout.addWidget(self.doItAllCheckbox)

		# ------------------------------
		# Add everything to the third column.
		# ------------------------------
		self.resForTypeLayout.addLayout(self.resLayout)
		self.resForTypeLayout.addLayout(self.modeLayout)
		self.resForTypeLayout.addLayout(self.fillSeamsLayout)
		self.resForTypeLayout.addLayout(self.addPrefixLayout)
		if not self.useMentalRay:
			self.resForTypeLayout.addWidget(self.autoLayoutLightmapUVs)
		self.resForTypeLayout.addWidget(self.bottomLine)
		self.resForTypeLayout.addWidget(self.psdCreationGroupBox)

		# ------------------------------
		# set them up.
		# ------------------------------
		self.columnThreeLayout.addLayout(self.resForTypeLayout)
		self.columnThreeLayout.setAlignment(Qt.AlignLeft)

		# ------------------------------
		# UV Preview UI Setup.
		# ------------------------------
		self.uvPreviewLayout = QVBoxLayout()

		self.uvPreviewLabel = QLabel('UV Preview:')
		self.uvPreviewLabel.setAlignment(Qt.AlignTop)

		self.reloadPreviewButton = QPushButton('Reload Preview')

		self.uvPreviewLayout.addWidget(self.uvPreviewLabel)
		self.uvPreviewLayout.addWidget(self.reloadPreviewButton)

		# ------------------------------
		# Main Window Ui Setup.
		# ------------------------------
		self.rightGridLayout.addWidget((self.objectsGroupBox),0,0)
		self.rightGridLayout.addWidget((self.renLayerGroupBox),0,1)
		self.rightGridLayout.addLayout((self.columnThreeLayout),0,2)
		# this will be added in at a later date
		#self.rightGridLayout.addLayout((self.uvPreviewLayout),0,3)

		self.rightGridGroupBox = QGroupBox('Render Set Details')
		self.rightGridGroupBox.setStyleSheet(GB_STYLE)
		self.rightGridGroupBox.setContentsMargins(5, 5, 5, 5)
		self.rightGridGroupBox.setLayout(self.rightGridLayout)

		self.bakeButton = QPushButton('BAKE')

		self.rightBoxLayout = QVBoxLayout()
		self.rightBoxLayout.setContentsMargins(0, 0, 0, 0)
		self.rightBoxLayout.addWidget(self.rightGridGroupBox)
		self.rightBoxLayout.addWidget(self.bakeButton)

		# ------------------------------
		# Add to gridLayout.
		# ------------------------------
		self.gridLayout.addWidget((self.renderSetsGroupBox),0,0)
		self.gridLayout.addLayout((self.rightBoxLayout),0,1)
		self.mainLayout.addItem(self.verticalSpacer)

		# ------------------------------
		# Callback Setup.
		# ------------------------------
		self.renderSetsListWidget.itemClicked.connect(self.GetRenderSets)
		self.renderSetsNewButton.clicked.connect(self.CreateNewRenderSet)
		self.renderSetsDeleteButton.clicked.connect(self.DeleteRenderSet)
		self.renderSetsRenameButton.clicked.connect(self.RenameRenderSet)
		self.toggleRenderableButton.clicked.connect(self.ToggleAllRenderMe)
		self.renderSetsSortButton.clicked.connect(self.SortRenderSet)
		self.validateRenderSetsButton.clicked.connect(self.ValidateRenderSets)
		self.autoPopulateSetsButton.clicked.connect(self.AutoPopulate)

		self.objectsGroupTreeWidget.itemClicked.connect(self.SingleSelectObject)
		self.uvSetRefreshButton.clicked.connect(partial(self.SetAllMeshUvSets, True))
		self.uvSetComboBox.currentIndexChanged.connect(self.ChangeMeshUvSet)
		self.objectsGroupLoadButton.clicked.connect(self.AddMeshToRenderSet)
		self.objectsGroupRemoveButton.clicked.connect(self.DeleteRenderSetMesh)
		self.objectsGroupSelectButton.clicked.connect(self.SelectMeshInRenderSet )

		self.renLayerTreeWidget.itemClicked.connect(self.SingleSelectRenLayer)
		self.layerBlendingComboBox.currentIndexChanged.connect(self.ChangeRenderLayerBlend)
		self.renLayerAddSelectedButton.clicked.connect(self.AddSelectedRenderLayer)
		self.renLayerAddSelectedToAllButton.clicked.connect(partial(self.AddSelectedRenderLayer, True))
		self.renLayerAddButton.clicked.connect(self.GetRenderLayers)
		self.renLayerRemoveButton.clicked.connect(self.DeleteRenderLayer)
		self.renLayerPopulateAllButton.clicked.connect(self.CopyRenderLayersToAllSets)
		self.upRenLayerButton.clicked.connect(self.MoveRenderLayer)
		self.downRenLayerButton.clicked.connect(partial(self.MoveRenderLayer, False))

		self.resComboBox.currentIndexChanged.connect(self.SetRenderSetResolution)
		self.modeComboBox.currentIndexChanged.connect(self.SetRenderSetColorMode)
		self.fillSeamsSlider.valueChanged.connect(self.SetRenderFillTextureSeams)
		self.addPrefixLineEdit.textChanged.connect(self.SetRenderSetLightMapPrefix)
		if not self.useMentalRay:
			self.autoLayoutLightmapUVs.clicked.connect(self.SetRenderSetLayoutUVs)
		self.combineImgCheckbox.clicked.connect(partial(SharedUtils.SetDisabledCheckBoxs,
																	self.combineImgCheckbox,
																	[self.hookUpLMTexturesCheckbox,
																	self.combineImgPrefixLabel,
																	self.combineImgPrefixLineEdit,
																	self.combineImgSuffixLabel,
																	self.combineImgSuffixLineEdit,
																	self.combineImgNoteLabel]))
		self.doItAllCheckbox.stateChanged.connect(self.DoNonVerbose)

		self.bakeButton.clicked.connect(self.BakeRenderLayers)

		self.SetRenderSetsDict()
		self.GetRenderSets()
		self.ValidateRenderSets()
		self.SetAllMeshUvSets()
		SharedUtils.RunFunctionOnTimer(1, self.RenderSetsSelectionCheck, parent=self.mainWindowName)

		# ------------------------------
		# Reload UI when new file is opened.
		# ------------------------------
		cmds.scriptJob(runOnce=True, event=('deleteAll', 'LightBakingTool.LightBakingTool().show()'), parent=self.mainWindowName)


	'''Right click menu for self.renderSetsListWidget'''
	def RenderSetsListContextMenu(self):
		rightMenu = QMenu(self.renderSetsListWidget)
		# Add LOCKED suffix to selected. #
		addLockedSuffix = QAction('Add _LOCKED Suffix to Selected', self, triggered=self.AddLockedSuffixToRenderSets)
		rightMenu.addAction(addLockedSuffix)
		# Duplicate selected with suffix. #
		duplicateSelected = QAction('Duplicate Selected with Suffix', self, triggered=self.DuplicateSelectedRenderSets)
		rightMenu.addAction(duplicateSelected)
		# Auto Set LM Resolution. #
		setResolution = QAction('Auto Set Resolution for Selected', self, triggered=self.AutoSetRenderSetResolution)
		rightMenu.addAction(setResolution)
		# Enable Auto Layout UV's. #
		enableLayoutUVs = QAction('Enable Auto Layout UVs', self, triggered=partial(self.ToggleAutoLayoutUVs, True))
		rightMenu.addAction(enableLayoutUVs)
		# Dissable Auto Layout UV's. #
		dissableLayoutUVs = QAction('Dissable Auto Layout UVs', self, triggered=partial(self.ToggleAutoLayoutUVs, False))
		rightMenu.addAction(dissableLayoutUVs)

		rightMenu.exec_(QCursor.pos())


	'''Add _LOCKED Suffix to end of selected renderSets'''
	def AddLockedSuffixToRenderSets(self):
		selectedRenderSets = self.renderSetsListWidget.selectedItems()

		if not selectedRenderSets:
			return

		for renderSet in selectedRenderSets:
			setName = renderSet.text()
			newSetName = '{}_LOCKED'.format(setName)

			if newSetName in list(self.renderSetsDict.keys()):
				cmds.warning('||||>>>> {} renderSet already exists, skipping!!! <<<<|||| '.format(newSetName))
				continue

			self.renderSetsDict[newSetName] = self.renderSetsDict.pop(setName)

		cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
		self.GetRenderSets(True, False)


	'''Duplicate selected renderSets and add suffix'''
	def DuplicateSelectedRenderSets(self):
		selectedRenderSets = self.renderSetsListWidget.selectedItems()

		if not selectedRenderSets:
			return

		prefix = '_LOCKED'
		prefixName = ''
		dialogResult = ''

		while prefixName == '' and dialogResult != 'Cancel':
			dialogResult = cmds.promptDialog(
					title='Prefix for duplicates',
					message='Enter Prefix:',
					text=prefix,
					button=['Continue', 'Cancel'],
					defaultButton='Continue',
					cancelButton='Cancel',
					dismissString='Cancel')

			prefixName = cmds.promptDialog(query=True, text=True)

		if dialogResult == 'Cancel':
			return

		for renderSet in selectedRenderSets:
			setName = renderSet.text()
			newSetName = '{}{}'.format(setName, prefixName)

			if newSetName in list(self.renderSetsDict.keys()):
				cmds.warning('||||>>>> {} renderSet already exists, skipping!!! <<<<|||| '.format(newSetName))
				continue

			self.renderSetsDict[newSetName] = self.renderSetsDict[setName]

		cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
		self.GetRenderSets(True, False)


	'''Check if there are multiple renderSets selected.'''
	def RenderSetsSelectionCheck(self):
		if len(self.renderSetsListWidget.selectedItems()) > 1:
			if self.rightGridGroupBox.isEnabled():
				self.rightGridGroupBox.setEnabled(False)
		else:
			if not self.rightGridGroupBox.isEnabled():
				self.rightGridGroupBox.setEnabled(True)


	'''Check if renderSets Object exists'''
	def CheckIfRenderSetsExist(self):
		if cmds.objExists(self.renderSetsName) and cmds.attributeQuery('notes', n=self.renderSetsName, exists=True):
			return True
		return False


	'''Check is Create PSD is Checked.'''
	def DoNonVerbose(self):
		if self.doItAllCheckbox.isChecked():
			self.createPSDtCheckbox.setChecked(True)
			self.combineImgCheckbox.setChecked(True)
			self.combineImgPrefixLabel.setEnabled(True)
			self.combineImgPrefixLineEdit.setEnabled(True)
			self.combineImgSuffixLabel.setEnabled(True)
			self.combineImgSuffixLineEdit.setEnabled(True)
			self.hookUpLMTexturesCheckbox.setDisabled(False)
			self.hookUpLMTexturesCheckbox.setChecked(True)
			self.combineImgNoteLabel.setEnabled(True)
			self.createUvSnapshotsCheckbox.setChecked(True)


	'''Get and set self.renderSetsDict if a renderSets node already exists in the scene.'''
	def SetRenderSetsDict(self):
		if self.CheckIfRenderSetsExist():
			dictInfo = cmds.getAttr(self.renderSetsName + '.notes')

			if dictInfo:
				self.renderSetsDict = eval(dictInfo)


	'''Get the RenderSets and populate the UI.'''
	def GetRenderSets(self, setRenderMe=True, multiSelectionCheck=True):
		if self.CheckIfRenderSetsExist():
			if setRenderMe:
				self.SetRenderMe()

			currentSel = ''

			if multiSelectionCheck and len(self.renderSetsListWidget.selectedItems()) > 1:
				self.rightGridGroupBox.setEnabled(False)
				return
			else:
				self.rightGridGroupBox.setEnabled(True)

			if self.renderSetsListWidget.currentItem():
				currentSel = self.renderSetsListWidget.currentItem().text()

			currentSelObj = ''
			selObjItems = self.objectsGroupTreeWidget.selectedItems()

			currentSelRenLayer = ''
			selRenLayerItems = self.renLayerTreeWidget.selectedItems()

			if len(selObjItems) == 1:
				for mesh in selObjItems:
					currentSelObj = mesh.text(0)

			if len(selRenLayerItems) == 1:
				for renLayer in selRenLayerItems:
					currentSelRenLayer = renLayer.text(0)

			notesAttr = cmds.getAttr(self.renderSetsName + '.notes')

			if notesAttr:
				renderSets = eval(notesAttr)

			self.renderSetsListWidget.clear()
			self.objectsGroupTreeWidget.clear()
			self.renLayerTreeWidget.clear()

			if renderSets:
				for renderSet in renderSets:
					item = QListWidgetItem(renderSet)
					item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

					if 'renderMe' in renderSets[renderSet]:
						if renderSets[renderSet]['renderMe'] is True:
							item.setCheckState(Qt.Checked)
						else:
							item.setCheckState(Qt.Unchecked)
					else:
						self.renderSetsDict[renderSet].setdefault('renderMe', True)
						item.setCheckState(Qt.Checked)

					self.renderSetsListWidget.addItem(item)
			# make sure the prevous selected
			if currentSel and currentSel in self.renderSetsDict:
				for index in range(self.renderSetsListWidget.count()):
					renderSetName = self.renderSetsListWidget.item(index).text()

					if renderSetName == currentSel:
						self.renderSetsListWidget.setCurrentRow(index)
						# add objects to QListWidget
						if 'objects' in self.renderSetsDict[renderSetName] and self.renderSetsDict[renderSetName]['objects']:
							for mesh in self.renderSetsDict[renderSetName]['objects']:
								uvSet = self.uvSets[self.renderSetsDict[renderSetName]['objects'][mesh]]
								treeWidgetItem = QTreeWidgetItem([mesh, uvSet])
								self.objectsGroupTreeWidget.addTopLevelItem(treeWidgetItem)
						# add renderlayers to QListWidget
						if 'renderLayers' in self.renderSetsDict[renderSetName] and self.renderSetsDict[renderSetName]['renderLayers']:
							for renLayer in self.renderSetsDict[renderSetName]['renderLayers']:
								blendType = self.blendTypes[self.renderSetsDict[renderSetName]['renderLayers'][renLayer]]
								treeWidgetItem = QTreeWidgetItem([renLayer, blendType])
								self.renLayerTreeWidget.addTopLevelItem(treeWidgetItem)
						break

				# set correct res from dict
				self.resComboBox.setCurrentIndex(self.renderSetsDict[currentSel]['resolution'])
				# set correct colorMode from dict
				self.modeComboBox.setCurrentIndex(self.renderSetsDict[currentSel]['colorMode'])
				# set correct fillTextureSeams from dict
				self.fillSeamsSlider.setValue(self.renderSetsDict[currentSel]['fillTextureSeams'])
				# set correct lightMapPrefix from dict
				self.addPrefixLineEdit.setText(self.renderSetsDict[currentSel]['lightMapPrefix'])
				# set Auto Layout UVs from dict
				if not self.useMentalRay and 'layoutUVs' in self.renderSetsDict[renderSet]:
					self.autoLayoutLightmapUVs.setChecked(self.renderSetsDict[currentSel]['layoutUVs'])

			if currentSelObj:
				iterator = QTreeWidgetItemIterator(self.objectsGroupTreeWidget)

				for item in iterator:
					objName = item.value().text(0)

					if objName == currentSelObj:
						self.objectsGroupTreeWidget.setCurrentItem(item.value())

			if currentSelRenLayer:
				iterator = QTreeWidgetItemIterator(self.renLayerTreeWidget)

				for item in iterator:
					layerName = item.value().text(0)

					if layerName == currentSelRenLayer:
						self.renLayerTreeWidget.setCurrentItem(item.value())


	'''
	Create renderSets object if needed.
	Will be created in the scene root with visibility off.
	'''
	def addRenderSetNode(self):
		if not cmds.objExists(self.renderSetsName):
			renderStatsNode = cmds.group(name=self.renderSetsName, empty=True)
			attrs = ['.tx','.ty','.tz','.rx','.ry','.rz','.sx','.sy','.sz','.v']

			for attr in attrs:
				if attr != '.v':
					cmds.setAttr(self.renderSetsName + attr, lock=True)
				else:
					cmds.setAttr(self.renderSetsName + attr, 0)

			self.createNotesAttr()


	'''Add the notes attr to the renderSets object if needed.'''
	def createNotesAttr(self):
		if not cmds.attributeQuery('notes', n=self.renderSetsName, exists=True):
			cmds.addAttr(self.renderSetsName, ln='notes', dt='string')
			cmds.setAttr(self.renderSetsName + '.notes', e=True, channelBox=True)
			cmds.setAttr(self.renderSetsName + '.notes', '{}', type='string')


	'''
	Dialog for nameing a RenderSets.
	Will Not allow duplicate names.
	'''
	def NewRenderSetDialog(self):
		name = ''
		result = []
		dialogPromptTitle = 'Name RenderSet!'
		dialogPromptMessage = 'Enter Name:'
		dialogResult = ''
		currentRenderSets = []

		for index in range(self.renderSetsListWidget.count()):
			currentRenderSets.append(self.renderSetsListWidget.item(index).text())

		while name == '' and dialogResult != 'Cancel':
			dialogResult = cmds.promptDialog(
					title=dialogPromptTitle,
					message=dialogPromptMessage,
					text=name,
					button=['Continue', 'Cancel'],
					defaultButton='Continue',
					cancelButton='Cancel',
					dismissString='Cancel')

			dialogPromptMessage = 'You MUST Enter A Name:'
			name = cmds.promptDialog(query=True, text=True)

			if currentRenderSets:
				for tag in currentRenderSets:
					if name == tag:
						dialogPromptMessage = 'That RenderSet Name is taken, try again:'
						name = ''

		result.append(dialogResult)
		result.append(name)
		return result


	'''Create a new RenderSet'''
	def CreateNewRenderSet(self, bypassDialog=False, newRenderSetName=[], bypassGetRenderSets=False):
		self.addRenderSetNode()

		if not bypassDialog:
			newRenderSetName = self.NewRenderSetDialog()

		if newRenderSetName[0] != 'Cancel' and cmds.objExists(self.renderSetsName):
			self.createNotesAttr()

			if self.renderSetsDict:
				addRenderSetKey = {newRenderSetName[1]:{}}
				self.renderSetsDict.update(addRenderSetKey)
			else:
				self.renderSetsDict[newRenderSetName[1]] = {}
			# set render set default Resolution
			self.renderSetsDict[newRenderSetName[1]].setdefault('resolution', 4)
			# set render set default Resolution
			self.renderSetsDict[newRenderSetName[1]].setdefault('colorMode', 0)
			# set render set default Resolution
			self.renderSetsDict[newRenderSetName[1]].setdefault('fillTextureSeams', 3.0)
			# set render set default Resolution
			self.renderSetsDict[newRenderSetName[1]].setdefault('lightMapPrefix', 'BAKE')
			# set render set default Resolution
			self.renderSetsDict[newRenderSetName[1]].setdefault('renderMe', True)
			# set Auto UV layout
			self.renderSetsDict[newRenderSetName[1]].setdefault('layoutUVs', False)

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')

			if not bypassGetRenderSets:
				self.GetRenderSets(True, False)


	'''Delete Selected RenderSet'''
	def DeleteRenderSet(self):
		selectedRenderSets = self.renderSetsListWidget.selectedItems()

		if not selectedRenderSets:
			return

		for renderSet in selectedRenderSets:
			setName = renderSet.text()
			self.renderSetsDict.pop(setName, None)
			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')

		self.GetRenderSets(True, False)


	'''Sort the RenderSet list'''
	def SortRenderSet(self):
		self.renderSetsListWidget.sortItems()


	'''Rename Selected RenderSet'''
	def RenameRenderSet(self):
		if len(self.renderSetsListWidget.selectedItems()) > 1:
			cmds.warning('Please select a single Render Set to Rename!')
			return
		if self.renderSetsListWidget.currentItem():
			setName = self.renderSetsListWidget.currentItem().text()
			index = self.renderSetsListWidget.currentRow()
			newTagName = self.NewRenderSetDialog()

			if newTagName[0] != 'Cancel':
				self.renderSetsDict[newTagName[1]] = self.renderSetsDict.pop(setName)
				cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
				self.GetRenderSets()


	'''Add selected mesh objects to current selected RenderSet'''
	def AddMeshToRenderSet(self, bypassSelected=False, setName='', meshs=[], bypassGetRenderSets=False):
		currentItem = True

		if not bypassSelected:
			meshs = cmds.listRelatives(cmds.ls(sl=True, dag=True, ni=True, type='mesh'),type='transform',p=True)
			currentItem = self.renderSetsListWidget.currentItem()

		if currentItem and meshs:
			if not bypassSelected:
				setName = self.renderSetsListWidget.currentItem().text()

			if not 'objects' in self.renderSetsDict[setName]:
				self.renderSetsDict[setName].setdefault('objects',{})

			for mesh in meshs:
				self.renderSetsDict[setName]['objects'].setdefault(mesh, self.GetCurrentUvSet(mesh))

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')

			if not bypassGetRenderSets:
				self.GetRenderSets()


	'''Get objects current UVSet'''
	def GetCurrentUvSet(self, mesh):
		uvSet = cmds.polyUVSet(mesh, q=True, currentUVSet=True)

		if uvSet:
			index = [i for i, s in enumerate(self.uvSets) if uvSet[0] in s]

			if not index:
				cmds.polyUVSet(mesh, currentUVSet=True, uvSet='map1')
				return 0
			else:
				return index[0]


	'''Delete the selected object(s) from the current RenderSet'''
	def DeleteRenderSetMesh(self):
		if self.renderSetsListWidget.currentItem() and self.objectsGroupTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()

			for mesh in self.objectsGroupTreeWidget.selectedItems():
				self.renderSetsDict[setName]['objects'].pop(mesh.text(0), None)

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''Select the current selected object(s) in the current RenderSet in the scene.'''
	def SelectMeshInRenderSet(self):
		if self.renderSetsListWidget.currentItem() and self.objectsGroupTreeWidget.selectedItems():
			cmds.select(cl=True)

			for mesh in self.objectsGroupTreeWidget.selectedItems():
				cmds.select(mesh.text(0), tgl=True)


	'''
	For changing the UVSet of the selected Object(s) in the current RenderSet.
	This WILL change the UVSet of the actual mesh object.
	'''
	def ChangeMeshUvSet(self):
		if self.renderSetsListWidget.currentItem() and self.objectsGroupTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()

			for mesh in self.objectsGroupTreeWidget.selectedItems():
				selectedItem = mesh.text(0)

				if cmds.objExists(selectedItem):
					uvSets = cmds.polyUVSet(selectedItem, q=True, allUVSets=True)

					if str(self.uvSetComboBox.currentText()) in uvSets:
						cmds.polyUVSet(selectedItem, currentUVSet=True, uvSet=str(self.uvSetComboBox.currentText()))
					elif str(self.uvSetComboBox.currentText()) not in uvSets:
						if str(self.uvSetComboBox.currentText()) == 'uvSet':
							cmds.polyUVSet(selectedItem, create=True, uvSet='uvSet')
							cmds.polyUVSet(selectedItem, currentUVSet=True, uvSet='uvSet')
						elif str(self.uvSetComboBox.currentText()) == 'uvSet1' and len(uvSets) == 2:
							cmds.polyUVSet(selectedItem, create=True, uvSet='uvSet1')
							cmds.polyUVSet(selectedItem, currentUVSet=True, uvSet='uvSet1')
						elif str(self.uvSetComboBox.currentText()) == 'uvSet1':
							cmds.polyUVSet(selectedItem, create=True, uvSet='uvSet')
							cmds.polyUVSet(selectedItem, create=True, uvSet='uvSet1')
							cmds.polyUVSet(selectedItem, currentUVSet=True, uvSet='uvSet1')

					self.renderSetsDict[setName]['objects'][selectedItem] = self.uvSetComboBox.currentIndex()

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''Return most common uvSet'''
	def ReturnCommonUvSet(self, renderSet):
		uvSets = []

		for obj in self.renderSetsDict[renderSet]['objects']:
			uvSets.append(self.uvSets[self.renderSetsDict[renderSet]['objects'][obj]])

		return max(set(uvSets), key = uvSets.count)


	'''Make sure all meshes are set to the correct uvSet'''
	def SetAllMeshUvSets(self, verbose=False):
		setsCheck = False

		if self.CheckIfRenderSetsExist():
			notesAttr = cmds.getAttr(self.renderSetsName + '.notes')
			renderSets = eval(notesAttr)

			if not renderSets:
				return

			for renderSet in renderSets:
				if not 'objects' in self.renderSetsDict:
					return
				if self.renderSetsDict[renderSet]['objects']:
					for obj in self.renderSetsDict[renderSet]['objects']:
						if not cmds.objExists(obj):
							continue

						uvSets = cmds.polyUVSet(obj, q=True, allUVSets=True)

						if not uvSets:
							print('\nWARNING--WARNING--WARNING--WARNING--WARNING--WARNING')
							print('--> The following object has no uvSets: ' + obj + ' <--')
							print('WARNING--WARNING--WARNING--WARNING--WARNING--WARNING\n')
							continue

						for set in self.uvSets:
							if set not in uvSets:
								cmds.polyUVSet(obj, create=True, uvSet=set)

						uvSet = self.uvSets[self.renderSetsDict[renderSet]['objects'][obj]]
						cmds.polyUVSet(obj, currentUVSet=True, uvSet=uvSet)

						if verbose:
							if not setsCheck:
								print('\n---=== Setting UVSets for all objects in RenderSets!!! ===---\n')
							print('--> ' + obj + ' = ' + uvSet)
						setsCheck = True
		if setsCheck:
			print('\n---=== UVSets have been set for all objects in RenderSets!!! ===---\n')


	'''For selecting a single object in the RenderSet'''
	def SingleSelectObject(self):
		if self.renderSetsListWidget.currentItem() and self.objectsGroupTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()
			selItems = self.objectsGroupTreeWidget.selectedItems()

			if len(selItems) == 1:
				for mesh in selItems:
					self.uvSetComboBox.setCurrentIndex(self.renderSetsDict[setName]['objects'][mesh.text(0)])

				cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
				self.GetRenderSets()


	'''Add renderLayers to current RenderSet.'''
	def AddRenderLayersToRenderSet(self, toAllSets=False):
		if self.renderSetsListWidget.currentItem():
			setName = self.renderSetsListWidget.currentItem().text()

			if not 'renderLayers' in self.renderSetsDict[setName]:
				self.renderSetsDict[setName].setdefault('renderLayers',{})

			renLayers = []
			iterator = QTreeWidgetItemIterator(self.renLayerTreeWidget)

			for item in iterator:
				renLayers.append(item.value().text(0))

			if renLayers:
				if toAllSets:
					allSets = []
					for index in range(self.renderSetsListWidget.count()):
						allSets.append(self.renderSetsListWidget.item(index).text())

					for set in allSets:
						if set != setName:
							if not 'renderLayers' in self.renderSetsDict[set]:
								self.renderSetsDict[set].setdefault('renderLayers',{})
							self.renderSetsDict[set]['renderLayers'].clear()

							for renLayer in renLayers:
								self.renderSetsDict[set]['renderLayers'].setdefault(renLayer, self.renderSetsDict[setName]['renderLayers'][renLayer])
				else:
					for renLayer in renLayers:
						self.renderSetsDict[setName]['renderLayers'].setdefault(renLayer, 0)

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''Create a new renderLayers in current Scene, and add to current RenderSet.'''
	def AddSelectedRenderLayer(self, allSets=False):
		currentLayer = cmds.editRenderLayerGlobals(query=True, currentRenderLayer=True)

		if currentLayer != 'defaultRenderLayer':
			treeWidgetItem = QTreeWidgetItem([currentLayer, 0])
			self.renLayerTreeWidget.addTopLevelItem(treeWidgetItem)

			if allSets:
				allSets = []
				for index in range(self.renderSetsListWidget.count()):
					allSets.append(self.renderSetsListWidget.item(index).text())

				for set in allSets:
					if not 'renderLayers' in self.renderSetsDict[set]:
						self.renderSetsDict[set].setdefault('renderLayers',{})

					currentLayers = self.renderSetsDict[set]['renderLayers']

					if currentLayer in currentLayers:
						continue

					self.renderSetsDict[set]['renderLayers'].setdefault(currentLayer, 0)

		self.AddRenderLayersToRenderSet()


	'''Get all renderLayers in current Scene, and add to current RenderSet.'''
	def GetRenderLayers(self):
		if cmds.objExists(self.renderSetsName):
			renderLayers = cmds.ls(type='renderLayer')
			self.renLayerTreeWidget.clear()

			if renderLayers:
				# dont add default render layer
				if 'defaultRenderLayer' in renderLayers:
					renderLayers.remove('defaultRenderLayer')

				for renderLayer in renderLayers:
					treeWidgetItem = QTreeWidgetItem([renderLayer, 0])
					self.renLayerTreeWidget.addTopLevelItem(treeWidgetItem)

			self.AddRenderLayersToRenderSet()


	'''Reorder the render layers so the PSD can be in the correct order.
	   self.renderSetsDict[setName]['renderLayers'] will be converted to an OrderedDict.
	'''
	def MoveRenderLayer(self, up=True):
		if self.renderSetsListWidget.currentItem() and self.renLayerTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()
			tempDict = OrderedDict()
			currentSelected = []

			for renLayer in self.renLayerTreeWidget.selectedItems():
				layerCount = 0
				iterator = QTreeWidgetItemIterator(self.renLayerTreeWidget)

				for item in iterator:
					layerCount += 1

				blendLayer = self.renderSetsDict[setName]['renderLayers'][renLayer.text(0)]
				index = self.renLayerTreeWidget.indexFromItem(renLayer).row()

				pos = index - 1

				if not up:
					pos = index + 1

				if pos <= 0:
					pos = 0
				elif pos >= (layerCount - 1):
					pos = layerCount - 1

				self.renLayerTreeWidget.takeTopLevelItem(index)
				self.renLayerTreeWidget.insertTopLevelItem(pos, renLayer)
				currentSelected.append(renLayer.text(0))

			iterator = QTreeWidgetItemIterator(self.renLayerTreeWidget)
			renLayers = []

			for item in iterator:
				renLayers.append(item.value().text(0))

			for renLayer in renLayers:
				if renLayer in self.renderSetsDict[setName]['renderLayers']:
					tempDict.setdefault(renLayer, self.renderSetsDict[setName]['renderLayers'][renLayer])

			self.renderSetsDict[setName]['renderLayers'] = tempDict

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()

			iterator = QTreeWidgetItemIterator(self.renLayerTreeWidget)
			# make sure they stay selected
			for item in iterator:
				if item.value().text(0) in currentSelected:
					item.value().setSelected(True)


	'''Remove renderLayer from selected RenderSet.'''
	def DeleteRenderLayer(self):
		if self.renderSetsListWidget.currentItem() and self.renLayerTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()

			for renLayer in self.renLayerTreeWidget.selectedItems():
				self.renderSetsDict[setName]['renderLayers'].pop(renLayer.text(0), None)

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''Copy all selected renderLayers from current RenderSet to all others.'''
	def CopyRenderLayersToAllSets(self):
		self.AddRenderLayersToRenderSet(True)


	'''Change the Blend Mode for selected renderLayer. This will be used in Photoshop.'''
	def ChangeRenderLayerBlend(self):
		if self.renderSetsListWidget.currentItem() and self.renLayerTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()

			for renLayer in self.renLayerTreeWidget.selectedItems():
				self.renderSetsDict[setName]['renderLayers'][renLayer.text(0)] = self.layerBlendingComboBox.currentIndex()

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''For selecting a single renderlayer in the selected RenderSet'''
	def SingleSelectRenLayer(self):
		if self.renderSetsListWidget.currentItem() and self.renLayerTreeWidget.selectedItems():
			setName = self.renderSetsListWidget.currentItem().text()
			selItems = self.renLayerTreeWidget.selectedItems()

			if len(selItems) == 1:
				for renLayer in selItems:
					self.layerBlendingComboBox.setCurrentIndex(self.renderSetsDict[setName]['renderLayers'][renLayer.text(0)])

				cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
				self.GetRenderSets()


	'''Set the value for the dictKeyName from a pyqtObj on selected RenderSet'''
	def SetRenderSetValue(self, dictKeyName, pyqtObj):
		if self.renderSetsListWidget.currentItem():
			setName = self.renderSetsListWidget.currentItem().text()

			self.renderSetsDict[setName][dictKeyName] = pyqtObj

			cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
			self.GetRenderSets()


	'''Set the resolution value for the selected RenderSet'''
	def SetRenderSetResolution(self):
		self.SetRenderSetValue('resolution', self.resComboBox.currentIndex())


	'''Set the colorMode value for the selected RenderSet'''
	def SetRenderSetColorMode(self):
		self.SetRenderSetValue('colorMode', self.modeComboBox.currentIndex())


	'''Set the fillTextureSeams float value for the selected RenderSet'''
	def SetRenderFillTextureSeams(self):
		self.SetRenderSetValue('fillTextureSeams', self.fillSeamsSlider.value())


	'''Set the Prefix for the selected RenderSet'''
	def SetRenderSetLightMapPrefix(self):
		self.SetRenderSetValue('lightMapPrefix', self.addPrefixLineEdit.text())


	'''Set Auto UV Layout'''
	def SetRenderSetLayoutUVs(self):
		if self.useMentalRay:
			return
		self.SetRenderSetValue('layoutUVs', self.autoLayoutLightmapUVs.isChecked())


	'''toggle the RenderMe Check Box for Render sets'''
	def SetRenderMe(self):
		for index in range(self.renderSetsListWidget.count()):
			if self.renderSetsListWidget.item(index).text() in self.renderSetsDict:
				if self.renderSetsListWidget.item(index).checkState() == Qt.Checked:
					self.renderSetsDict[self.renderSetsListWidget.item(index).text()]['renderMe'] = True
				else:
					self.renderSetsDict[self.renderSetsListWidget.item(index).text()]['renderMe'] = False

				cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')


	'''toggle the RenderMe Check Box for Render sets'''
	def ToggleAllRenderMe(self):
		if self.renderSetsListWidget.count() == 0:
			return
		state = True

		if self.renderSetsListWidget.item(0).checkState() == Qt.Checked:
			state = False

		for index in range(self.renderSetsListWidget.count()):
			if self.renderSetsListWidget.item(index).text() in self.renderSetsDict:
				self.renderSetsDict[self.renderSetsListWidget.item(index).text()]['renderMe'] = state

				cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')

		self.GetRenderSets(False)


	'''
	Validate that the current objects and renderLayers still exisit in the Scene.
	'''
	def ValidateRenderSets(self):
		ValPass = True

		if self.CheckIfRenderSetsExist():
			# get the library info
			notesAttr = cmds.getAttr(self.renderSetsName + '.notes')

			renderSets = eval(notesAttr)

			invalidObjects = {}
			invalidObjectsList = []
			invalidObjectsString = ''
			dialogPromptMessage = ''
			fixMeMessage = 'Would you like to remove these from there corresponding Render Sets?\nYou CAN NOT bake until this is fixed!!!!'

			if renderSets:
				for renderSet in renderSets:
					for key in ['objects', 'renderLayers']:
						if key in self.renderSetsDict[renderSet] and self.renderSetsDict[renderSet][key]:
							for obj in self.renderSetsDict[renderSet][key]:
								invalid = False

								if not cmds.objExists(obj):
									invalid = True
								elif key == 'objects' and not cmds.listRelatives(obj, ad=True, f=True, ni=True, type='mesh'):
									invalid = True

								if invalid:
									if not renderSet in invalidObjects:
										addRenderSetKey = {renderSet:{}}
										invalidObjects.update(addRenderSetKey)

									if not key in invalidObjects[renderSet]:
										invalidObjects[renderSet].setdefault(key,[])

									invalidObjects[renderSet][key].append(obj)

				if invalidObjects:
					for renderSet in invalidObjects:
						invalidObjectsString = renderSet + ' : '

						for key in ['objects', 'renderLayers']:
							if key in invalidObjects[renderSet]:
								invalidObjectsString += key + ' --> \n'
								listCount = len(invalidObjects[renderSet][key])

								for i in range(len(invalidObjects[renderSet][key])):
									divider = '\n'

									if i == (len(invalidObjects[renderSet][key]) - 1):
										divider = ''

									invalidObjectsString += invalidObjects[renderSet][key][i] + divider

						invalidObjectsList.append(invalidObjectsString)

				if invalidObjects:
					dialogResult = cmds.layoutDialog(ui=lambda *args: SharedUtils.UniversalConfirmDialog(True,
																		'Invalid Objects found in the following Render Sets:\n{}'.format(fixMeMessage),
																		invalidObjectsList))
					if dialogResult == 'CONTINUE':
						for renderSet in invalidObjects:
							for key in ['objects', 'renderLayers']:
								if key in invalidObjects[renderSet]:
									for obj in invalidObjects[renderSet][key]:
										self.renderSetsDict[renderSet][key].pop(obj, None)

						cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
						self.GetRenderSets()

					else:
						ValPass = False

		return ValPass


	'''Bake out the light maps for each RenderSet. There will be 1 lightmap per RenderLayers in RenderSet'''
	def BakeRenderLayers(self):
		continueWithBake = cmds.confirmDialog(title='Confirm Bake!', message='Are you sure You want to continue with Bake?', button=['Yes','No'], defaultButton='Yes', cancelButton='No', dismissString='No')

		if continueWithBake == 'No':
			cmds.warning('Bake Canceled!')
			return

		if self.useMentalRay:
			# Check is the initBakeSets exsist yet, if not, create them.
			if not cmds.objExists('initialTextureBakeSet'):
				mel.eval('createBakeSet("initialTextureBakeSet", "textureBakeSet");')
			if not cmds.objExists('initialVertexBakeSet'):
				mel.eval('createBakeSet("initialVertexBakeSet", "textureBakeSet");')

		if self.CheckIfRenderSetsExist():
			validationPass = self.ValidateRenderSets()

			if not validationPass:
				cmds.warning('Bake Canceled, did not pass Validation. :(')
				return
			# gather all light transforms
			lightShapes = cmds.ls(type='light')
			lights = cmds.listRelatives(lightShapes, type='transform', p=True)

			self.SetAllMeshUvSets()
			# get the library info
			notesAttr = cmds.getAttr(self.renderSetsName + '.notes')
			# get current RenderLayer
			currentRenderLayer = cmds.editRenderLayerGlobals(query=True, currentRenderLayer=True)
			# hook up lightmap textures dict.
			hookUpLMTexturesDict = {}
			# Failed lightmap List #
			failedLightMap = []

			renderSets = eval(notesAttr)

			if renderSets:
				# create textures/LM folder structure if needed
				fileLoc = cmds.file(q=True, sn=True)
				currentFolder = os.path.dirname(fileLoc)
				textureFolder = os.path.dirname(currentFolder) + '/textures'
				# create textures folder
				SharedUtils.CreateDir(textureFolder)

				for renderSet in renderSets:
					self.currentRenderset = renderSet
					renLayersReturn = 'dismiss'
					if self.renderSetsDict[renderSet]['renderMe']:
						if 'renderLayers' in self.renderSetsDict[renderSet] and self.renderSetsDict[renderSet]['renderLayers']:
							if 'objects' in self.renderSetsDict[renderSet] and self.renderSetsDict[renderSet]['objects']:
								renLayersReturn = str(list(self.renderSetsDict[renderSet]['renderLayers'].keys()))

								if self.doItAllCheckbox.isChecked() == False:
									renLayersReturn = cmds.layoutDialog(ui=self.SetRenderLayerConfirmDialog)

								allRenLayers = list(self.renderSetsDict[renderSet]['renderLayers'].keys())

								if renLayersReturn == 'dismiss':
									self.PrintMessage(renderSet + ' is being skipped!')
									continue

								# convert to list and remove unicode
								renLayersReturn = [str(x) for x in ast.literal_eval(renLayersReturn)]

								cmds.select(cl=True)
								# get texture resolution
								res = int(self.resComboBox.itemText(self.renderSetsDict[renderSet]['resolution']))
								padding = self.renderSetsDict[renderSet]['fillTextureSeams']

								if self.useMentalRay:
									# create temp bake set
									tmpBakeSet = mel.eval('createBakeSet("' + renderSet + 'TexturesBakeSet", "textureBakeSet");')
									# add objects to temp bake set.
									for mesh in self.renderSetsDict[renderSet]['objects']:
										mel.eval('assignBakeSet("' + tmpBakeSet + '", "' + mesh + '");')

									# set texture res of temp bake set
									cmds.setAttr(tmpBakeSet + '.xResolution', res)
									cmds.setAttr(tmpBakeSet + '.yResolution', res)
									# set Color Mode of bake set
									cmds.setAttr(tmpBakeSet + '.colorMode', self.renderSetsDict[renderSet]['colorMode'])
									# set Fill Texture Seams value for bake set
									cmds.setAttr(tmpBakeSet + '.fillTextureSeams', padding)
									# set To TIFF defaultFileSaveType
									cmds.setAttr(tmpBakeSet + '.fileFormat', 6)
									# make sure there is only one map
									cmds.setAttr(tmpBakeSet + '.bakeToOneMap', 1)

								imageFileInfo = []
								tifFileList = []
								layerIndex = 0

								for renLayer in renLayersReturn:
									setLayerString = '{}_{}'.format(renderSet, renLayer)
									lightMapName = self.renderSetsDict[renderSet]['lightMapPrefix'] + '_' + setLayerString + '_LM'
									cmds.editRenderLayerGlobals(currentRenderLayer=renLayer)
									setMembers = cmds.editRenderLayerMembers(renLayer, query=True)

									if setMembers is None:
										setMembers = []

									objsToAdd = []
									# add object to render layer if needed
									for obj in self.renderSetsDict[renderSet]['objects']:
										if obj not in setMembers:
											objsToAdd.append(obj)
											print('>-----=====| ' + obj + ' added to RenderLayer ' + renLayer + ' |=====-----<')

									if objsToAdd:
										if self.useMentalRay:
											cmds.editRenderLayerMembers(renLayer, objsToAdd, nr=True)
										else:
											#self.AddObjectToCollection(renLayer, MISSING_OBJ_COL, objsToAdd)
											cmds.editRenderLayerMembers(renLayer, objsToAdd, nr=True)

									ext = '.tif'

									if self.useMentalRay:
										# Select the temp bake set
										cmds.setAttr(tmpBakeSet + '.prefix', lightMapName, type='string')
										cmds.select(tmpBakeSet)
										# do some sweet magic
										cmds.convertLightmapSetup(camera='persp', sh=True, keepOrgSG=True, showcpv=True, prj=textureFolder)
									else:
										# Add ShaderOverride to Collections if needed.
										self.AddShaderOverridesIfNeeded()
										#ext = '.exr'
										meshes = list(self.renderSetsDict[renderSet]['objects'].keys())
										exrPath = textureFolder + '/lightMap'
										uvSet = self.ReturnCommonUvSet(renderSet)
										SharedUtils.CreateDir(exrPath)
										layoutUVs = False
										# gather all light transforms
										allLights = cmds.ls(lights=True, long=True)
										allLightTransforms = list(set(cmds.listRelatives(allLights, parent=True, fullPath=True) if allLights else []))
										allNodes = cmds.ls(long=True)
										arnoldLightTypes = ['aiAreaLight', 'aiSkyDomeLight', 'aiMeshLight', 'aiPhotometricLight', 'aiLightPortal']
										arnoldLights = [node for node in allNodes for lightType in arnoldLightTypes if lightType in cmds.nodeType(node)]
										arnoldLightTransforms = cmds.listRelatives(arnoldLights, parent=True, fullPath=True) if arnoldLights else []
										lights = list(set(allLightTransforms + arnoldLightTransforms))

										if 'layoutUVs' in self.renderSetsDict[renderSet]:
											layoutUVs = self.renderSetsDict[renderSet]['layoutUVs']
										lightMapName = self.ArnoldLightmapBake(meshes,
																			   res,
																			   padding,
																			   lightMapName,
																			   renLayer,
																			   exrPath,
																			   uvSet,
																			   lights,
																			   layoutUVs)

									fileName = '{}/lightMap/{}{}'.format(textureFolder, lightMapName, ext)

									if not os.path.isfile(fileName):
										self.PrintMessage('{} has been Skipped, {}{} could not be created!'.format(setLayerString,
																													lightMapName,
																													ext))
										failedLightMap.append('{}_{} ---> {}{}'.format(renderSet, renLayer, lightMapName, ext))
										continue

									tifFileList.append(os.path.abspath(fileName))
									self.PrintMessage(setLayerString + ' has been baked and saved to: ' + fileName)

									imageFileInfo.append([fileName, renLayer, layerIndex])
									layerIndex += 1

								if self.useMentalRay:
									# delete the bakeSet
									cmds.delete(tmpBakeSet)

								psdLoc = textureFolder + '/lightMap/' + renderSet + '.psd'
								psdPathExists = False

								if not tifFileList:
									self.PrintMessage(renderSet + '.psd creation has been skipped, no tif files created to use!!!')
									continue

								if os.path.exists(psdLoc):
									psdPathExists = True

								# create PSD
								if self.createPSDtCheckbox.isChecked():
									if self.doItAllCheckbox.isChecked() == False:
										if len(renLayersReturn) != len(allRenLayers):
											self.PrintMessage(renderSet + '.psd creation has been skipped, must have all RenderLayers selected to create!!!')
											continue

										if psdPathExists:
											self.PrintMessage('=== Overwriting PSD===')
											#continuePSDCreation = cmds.confirmDialog(title='Continue with PSD Creation', message= renderSet + '.psd already exisit, are you sure you want to overwrite it?', button=['Yes','No'], defaultButton='Yes', cancelButton='No', dismissString='No')
											#if continuePSDCreation == 'No':
											#	self.PrintMessage(renderSet + '.psd creation has been skipped!!!')
											#	continue

									# Reverse it so the Psd layers are the correct order
									#imageFileInfo.reverse()
									maxIndex = max(sublist[2] for sublist in imageFileInfo)
									for sublist in imageFileInfo:
										sublist[2] = maxIndex - sublist[2]

									# Close and delete the existing psd to allow for canvas size override
									try:
										print ("Linking to Photoshop instance")
										psApp = comtypes.client.GetActiveObject('Photoshop.Application', dynamic=True)
									except Exception as e:
										print ("Creating Photoshop instance")
										psApp = comtypes.client.CreateObject('Photoshop.Application', dynamic=True)
										psApp.Visible = True
									if psApp:
										document_count = psApp.Documents.Count
										for i in range(document_count):
											doc = psApp.Documents[i+1]
											try:
												normalizedDocPath = os.path.normpath(doc.FullName).lower()
												normalizedPsdPath = os.path.normpath(psdLoc).lower()
											except Exception as e:
												print(f"Skipped doc {doc.Name}: {e}")
												continue
											if normalizedDocPath == normalizedPsdPath:
												try:
													doc.Close(2)
													if os.path.exists(psdLoc):
														os.remove(psdLoc)
												except Exception as e:
													pass
												break
									else:
										pass

									# Add TIFFs to PSD
									cmds.psdTextureFile(xr=res, yr=res, ifn=(imageFileInfo), psf=psdLoc)
	
									self.PrintMessage('A PSD has been created and saved to: ' + psdLoc)
									
									psdPathExists = True

									# Make adjustments to PSD
									self.ProcessPSDFile(os.path.normpath(psdLoc), OrderedDict([(str(k), v) for k, v in list(self.renderSetsDict[renderSet]['renderLayers'].items())]), tifFileList,)

								# Create PNG from PSD
								if self.combineImgCheckbox.isChecked():
									if not psdPathExists:
										self.PrintMessage(renderSet + '.psd does not exsist, Skipping PNG Creation!!!')
										continue

									# create LM folder if needed
									if not os.path.exists(textureFolder + '/LM'):
										os.makedirs(textureFolder + '/LM')

									prefix = ''
									suffix = ''

									if self.combineImgPrefixLineEdit.text():
										prefix = self.combineImgPrefixLineEdit.text() + '_'
									if self.combineImgSuffixLineEdit.text():
										suffix = '_' + self.combineImgSuffixLineEdit.text()

									pngName = prefix + renderSet + suffix
									pngLoc = textureFolder + '/LM/' + pngName + '.png'
									
									cmds.psdExport(ifn=psdLoc, ofn=pngLoc, format='png')
									self.PrintMessage(pngLoc + ' has been created or updated!!!')

									if self.hookUpLMTexturesCheckbox.isChecked():
										hookUpLMTexturesDict.update({renderSet:{}})

										for mesh in self.renderSetsDict[renderSet]['objects']:
											hookUpLMTexturesDict[renderSet].setdefault(mesh, pngLoc)

								if self.createUvSnapshotsCheckbox.isChecked():
									uvSnapShotsFolder = textureFolder + '/uvSnapshots'
									uvSnapshotName = uvSnapShotsFolder + '/' + renderSet + '_uvSnap' + '.png'

									# create uvSnapshots folder if needed
									if not os.path.exists(uvSnapShotsFolder):
										os.makedirs(uvSnapShotsFolder)

									cmds.select(cl=True)
									cmds.select(list(self.renderSetsDict[renderSet]['objects'].keys()))
									print('------------=======<<<<<<< uvSnapshot render >>>>>>>=======------------')
									cmds.uvSnapshot(n=uvSnapshotName, aa=True, xr=res, yr=res, o=True, ff='png')
									print('------------=======<<<<<<< uvSnapshot render >>>>>>>=======------------\n')
									cmds.select(cl=True)

							else:
								self.PrintMessage(renderSet + ' is being skipped due to NO Objects loaded!')
						else:
							self.PrintMessage(renderSet + ' is being skipped due to NO Renderlayers being loaded!')

			# set back to the current render layer
			cmds.editRenderLayerGlobals(currentRenderLayer=currentRenderLayer)

			if hookUpLMTexturesDict:
				cmds.editRenderLayerGlobals(currentRenderLayer='defaultRenderLayer')
				# Enable EuseLightmap if needed.
				self.EnableUseLightmap(hookUpLMTexturesDict)
				# Because we need to give the enabled settings a moment to register. #
				cmds.pause(sec=5)
				# Hook up the lightmap png files back to the materials.
				self.HookUpLightMaps(hookUpLMTexturesDict)

			self.PrintMessage('            --== BAKE COMPLETE, PLEASE LOOK ABOVE FOR DETAILS! ==--')

			if failedLightMap:
				cmds.layoutDialog(ui=lambda *args: SharedUtils.UniversalConfirmDialog(False,
																	'The following lightmaps failed:',
																	failedLightMap))


	'''
	Seems to work better if this is its own function.
	Note: Not combined with HookUpLightMaps for a reason.
	'''
	def EnableUseLightmap(self, dict={}):
		if dict == {}:
			print('<<<<<<<< Materials Dict is Empty, no Light Maps to hook up!>>>>>>>>')
			return
		print('\n||||||||>>>>>>>> Start Enable UseLightmap <<<<<<<<||||||||\n')
		for key in dict:
			for mesh in dict[key]:
				shapeNode = SharedUtils.GetShape(mesh)

				if shapeNode == False:
					print('<<<<<< WARNING - No shapeNode found, skipping ' +  mesh + ' >>>>>>')
					continue

				if type(shapeNode) is list:
					shapeNode = [x for x in shapeNode if not x.rstrip(string.digits).endswith("Orig")]

					if len(shapeNode) == 1:
						shapeNode = shapeNode[0]
					else:
						print('<<<<<< WARNING - No shapeNode or more than one found, skipping ' +  mesh + ' >>>>>>')
						continue

				shadeEng = cmds.listConnections(shapeNode, type='shadingEngine')
				materials = cmds.ls(cmds.listConnections(list(set(shadeEng))), materials=True)

				if not materials:
					print('<<<<<< WARNING - No Materials found, skipping ' +  mesh + ' >>>>>>')
					continue

				for material in materials:
					if key.lower().endswith('_locked'):
						self.EnableShaderFxSettings(material, ['UseLightmap', 'UseLockedLightmap'])
					else:
						self.EnableShaderFxSettings(material, ['UseLightmap'])

		print('\n||||||||>>>>>>>> End Enable UseLightmap  <<<<<<<<||||||||\n')


	'''Hook the light maps up to there respective material.'''
	def HookUpLightMaps(self, dict={}):
		if dict == {}:
			print('<<<<<<<< Materials Dict is Empty, no Light Maps to hook up!>>>>>>>>')
			return
		print('\n||||||||>>>>>>>> Start LM Hookup <<<<<<<<||||||||\n')
		for key in dict:
			for mesh in dict[key]:
				shapeNode = SharedUtils.GetShape(mesh)

				if shapeNode == False:
					print('<<<<<< WARNING - No shapeNode found, skipping ' +  mesh + ' >>>>>>')
					continue

				if type(shapeNode) is list:
					shapeNode = [x for x in shapeNode if not x.rstrip(string.digits).endswith("Orig")]

					if len(shapeNode) == 1:
						shapeNode = shapeNode[0]
					else:
						print('<<<<<< WARNING - No shapeNode or more than one found, skipping ' +  mesh + ' >>>>>>')
						continue

				shadeEng = cmds.listConnections(shapeNode, type='shadingEngine')
				materials = cmds.ls(cmds.listConnections(list(set(shadeEng))), materials=True)

				if not materials:
					print('<<<<<< WARNING - No Materials found, skipping ' +  mesh + ' >>>>>>')
					continue

				for material in materials:
					if key.lower().endswith('_locked'):
						if cmds.attributeQuery('LockLM', node=material, exists=True):
							cmds.setAttr((material + '.LockLM'), dict[key][mesh], type='string')
							print('<<<<<<<< ' + material + '.LockLM :: ' + dict[key][mesh] + ' >>>>>>>>')
					else:
						for attr in ['LightmapMap', 'Lightmap']:
							if cmds.attributeQuery(attr, node=material, exists=True):
								cmds.setAttr((material + '.' + attr), dict[key][mesh], type='string')
								print('<<<<<<<< ' + (material + '.' + attr) + ' :: ' + dict[key][mesh] + ' >>>>>>>>')

		print('\n||||||||>>>>>>>> End LM Hookup <<<<<<<<||||||||\n')


	''' Set ShaderFx Setting bool to True. '''
	def EnableShaderFxSettings(self, material, settings=[]):
		if not settings:
			return

		for setting in settings:
			try:
				temp = cmds.shaderfx(sfxnode=material, getNodeIDByName=setting)
				isEnabled = cmds.shaderfx(sfxnode=material, getPropertyValue=(int(temp), 'value'))

				if not isEnabled:
					cmds.shaderfx(sfxnode=material, edit_bool=(int(temp), 'value', True))
					print('<<<<<<<< ' + material + '.' + setting + ' :: True >>>>>>>>')
			except:
				return


	'''Instal comtypes to tools/Python2 in needed.'''
	def InstallComtypesIfNeeded(self):
		comtypes = 'C:/tools/Python2/Lib/site-packages/comtypes'

		if platform.system() != 'Windows':
			# need to put the correct Dir here
			comtypes = 'C:/tools/Python2/Lib/site-packages/comtypes'

		if os.path.exists(comtypes):
			return

		cmds.warning('comtypes has been installed to your Windows Python site-packages Dir!!!')
		cmd = ['pip', 'install', 'comtypes']
		p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)

		for line in p.stdout:
			print(line)

		p.wait()
		self.PrintMessage('***** comtypes has been installed to your Windows Python site-packages Dir!!! *****')


	'''Select RenderLayers to bake if not all are needed'''
	def SetRenderLayerConfirmDialog(self):
		form = cmds.setParent(q=True)
		cmds.formLayout(form, e=True, width=300)

		t = cmds.text(l='Deselect any Render Layers you "DO NOT" wish to bake!')
		tsl = cmds.textScrollList('renderLayersList', allowMultiSelection=True)
		b1 = cmds.button(l='Continue With Selected!', c=lambda *args: cmds.layoutDialog(dismiss=str(cmds.textScrollList('renderLayersList', q=1, si=1))))
		b2 = cmds.button(l='Skip RenderSet!', c='cmds.layoutDialog(dismiss="dismiss")')

		spacer = 5

		cmds.formLayout(form, edit=True,
										attachForm=[(t, 'top', 20), (t, 'left', spacer), (t, 'right', spacer), (b1, 'left', spacer), (b2, 'right', spacer), (tsl, 'bottom', spacer), (tsl, 'left', spacer), (tsl, 'right', spacer)],
										attachNone=[(t, 'bottom'), (b1, 'bottom'), (b2, 'bottom')],
										attachControl=[(tsl, 'top', spacer, t), (b1, 'top', spacer, tsl), (b2, 'top', spacer, tsl)],
										attachPosition=[(b1, 'right', spacer, 50), (b2, 'left', spacer, 50), (b2, 'right', spacer, 100), (tsl, 'bottom', spacer, 88)])

		for child in self.renderSetsDict[self.currentRenderset]['renderLayers']:
			cmds.textScrollList('renderLayersList', a=child,e=1, si=child)


	'''Create RenderSets based on data from GatherAutoPopulateData().'''
	def AutoPopulate(self):
		autoPopulateDict = self.GatherAutoPopulateData()

		if autoPopulateDict == None:
			return

		for key in autoPopulateDict:
			self.CreateNewRenderSet(True, ['Continue', key], True)

		for key in autoPopulateDict:
			self.AddMeshToRenderSet(True, key, autoPopulateDict[key], True)

		self.GetRenderSets(True, False)
		self.AutoSetRenderSetResolution(False)


	'''
	Garther Data to create RenderSets with included meshs.
	Only Uses RM_ objects.
	'''
	def GatherAutoPopulateData(self):
		rooms = cmds.ls(sl=True)

		if any([ x for x in rooms if not x.startswith('RM_') ]) or not rooms:
			cmds.warning('Canceled, please only select RM_ objects.')
			return None

		dict = {}

		for room in rooms:
			roomName = room.split('_')[-1]
			tag = re.sub('[^A-Z]', '', roomName + '_')
			# if tage is only lenth 2, use the full Room name.
			tag = tag if len(tag) > 2 else roomName + '_'

			types = cmds.listRelatives(room, f=True)

			if not types:
				print(room + ' has been skipped!')
				continue

			for type in types:
				if any(s in type for s in ('UpgradeObjects', 'ActionSlots')):
					continue

				prefix = type.split('|')[-1]
				grps = cmds.listRelatives(type, f=True)

				if not grps:
					continue

				for grp in grps:
					meshObjects = []

					if grp.endswith('NavMeshObstacles'):
						continue

					suffix = grp.split('|')[-1]
					shapeNodes = cmds.listRelatives(grp, ad=True, f=True, ni=True, type='mesh')

					if not shapeNodes:
						continue

					for node in shapeNodes:
						mesh = cmds.listRelatives(node, type='transform', p=True)
						mesh = [x for x in mesh if not '_ShadowObject' in x]

						if not mesh:
							continue

						meshObjects.append(mesh[0])

					if meshObjects:
						dict[tag + prefix + '_' + suffix + '_LM'] = meshObjects

		return dict


	'''Toggle auto layout UV's for selected Render Sets'''
	def ToggleAutoLayoutUVs(self, enable=True):
		if not self.CheckIfRenderSetsExist():
			cmds.warning('No RenderSets Found!!')
			return

		selectedRenderSets = self.renderSetsListWidget.selectedItems()

		if not selectedRenderSets:
			return
		selectedRenderSets = [match.text() for match in selectedRenderSets if match.text()]

		dictInfo = cmds.getAttr(self.renderSetsName + '.notes')
		renderSets = eval(dictInfo)

		for renderSet in renderSets:
			if not renderSet in selectedRenderSets:
				continue

			self.renderSetsDict[renderSet]['layoutUVs'] = enable
			print('{} -- Auto Layout UVs set to {}'.format(renderSet, enable))

		cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
		self.GetRenderSets(True, True)


	'''Auto set texture resolution based on objects in Render Set.'''
	def AutoSetRenderSetResolution(self, selected=True):
		if not self.CheckIfRenderSetsExist():
			cmds.warning('No RenderSets Found!!')
			return

		selectedRenderSets = []

		if selected:
			selectedRenderSets = self.renderSetsListWidget.selectedItems()
			selectedRenderSets = [match.text() for match in selectedRenderSets if match.text()]

		dictInfo = cmds.getAttr(self.renderSetsName + '.notes')
		renderSets = eval(dictInfo)

		for renderSet in renderSets:
			objects = self.renderSetsDict[renderSet]['objects']

			if not objects:
				continue

			if selected and not renderSet in selectedRenderSets:
				continue

			size = 0
			for obj in objects:
				bbox = cmds.exactWorldBoundingBox(obj)
				size += (bbox[3]-bbox[0] + bbox[4]-bbox[1]  + bbox[5]-bbox[2]) / 3

			resolution = 0
			resString = '64'
			if size > 1500:
				resolution = 4
				resString = '1024'
			elif size > 700:
				resolution = 3
				resString = '512'
			elif size > 300:
				resolution = 2
				resString = '256'
			elif size > 80:
				resolution = 1
				resString = '128'
			self.renderSetsDict[renderSet]['resolution'] = resolution
			print('{} -- Resolution set to {}'.format(renderSet, resString))

		cmds.setAttr(self.renderSetsName + '.notes', self.renderSetsDict, type='string')
		self.GetRenderSets(True, selected)


	'''Add object to missing objs collection'''
	def AddObjectToCollection(self, layerName, colName, objs):
		if not objs:
			return

		layerName = self.UpdateRenderlayerName(layerName)
		renderLayer = renderSetup.instance().getRenderLayer(layerName)
		collectionNames = self.RetrunCollectionNames(layerName)

		exists = [x for x in collectionNames if x.startswith(colName)]

		if exists:
			collection = renderLayer.getCollectionByName(exists[0])
		else:
			collection = renderLayer.createCollection(colName)

		collection.getSelector().staticSelection.set(objs)


	'''Return the desired RenderLayer Connection by name'''
	def RetrunCollectionNames(self, layerName):
		layerName = self.UpdateRenderlayerName(layerName)
		renderLayer = renderSetup.instance().getRenderLayer(layerName)

		collections = renderLayer.getCollections()
		collectionNames = []

		for col in collections:
			collectionNames.append(col.name())

		return collectionNames


	'''Make sure RenderLayer Name is not the old system nameing'''
	def UpdateRenderlayerName(self, layerName):
		if layerName.startswith('rs_'):
			layerName = layerName[3:]

		return layerName


	'''Delete the desired RenderLayer Connection'''
	def DeleteCollection(self, layerName, colName):
		layerName = self.UpdateRenderlayerName(layerName)
		renderLayer = renderSetup.instance().getRenderLayer(layerName)
		collectionNames = self.RetrunCollectionNames(layerName)

		if colName in collectionNames:
			collection = renderLayer.getCollectionByName(colName)
			collectionTool.delete(collection)


	'''Return all renderlayer names'''
	def RetrunRenderLayerNames(self):
		renderLayers = renderSetup.instance().getRenderLayers()
		layerNames = []

		for layer in renderLayers:
			layerNames.append(layer.name())

		return layerNames


	'''
	Add Shader Override collection and Override if needed.
	'''
	def AddShaderOverridesIfNeeded(self):
		rs = renderSetup.instance()
		layers = rs.getRenderLayers()

		for layer in layers:
			collections = layer.getCollections()

			for collection in collections:
				shadingEng = collection.getCollections()
				createOverrideMat = True

				for shade in shadingEng:
					type = shade.getSelector().getFilterType()

					if type == 11:
						createOverrideMat = False

				if not createOverrideMat:
					continue
				# Check if set to all #
				currentType = collection.getSelector().getFilterType()
				tempTypeChange = False
				# Set to transform instead #
				if currentType == 0:
					collection.getSelector().setFilterType(1)
					tempTypeChange = True
				# Create aiLambert_OverrideShader if needed #
				if not cmds.objExists('aiLambert_OverrideShader'):
					cmds.createNode('aiLambert', n='aiLambert_OverrideShader')

				shaderOverride = collection.createOverride('aiLambert', 'shaderOverride')
				overrideName = shaderOverride.name()
				cmds.connectAttr('aiLambert_OverrideShader.outColor', '{}.attrValue'.format(overrideName), f=True)

				if tempTypeChange:
					collection.getSelector().setFilterType(currentType)


	'''Bake Lightmaps using Arnold'''
	def ArnoldLightmapBake(self, meshes, resolution, padding, combinedName,renderLayer, dirPath, uvSet, lights, layoutUVs):
		if not meshes:
			return
		# switch to current render layer
		cmds.editRenderLayerGlobals(currentRenderLayer=renderLayer)
		# triggered if 'Auto Layout Lightmap UVs' is checked
		if layoutUVs:
			for mesh in meshes:
				uvSets = cmds.polyUVSet(mesh, query=True, allUVSets=True)
				cmds.polyCopyUV(mesh, uvSetNameInput=uvSets[0], uvSetName=uvSet, ch=True)
			cmds.polyMultiLayoutUV(meshes, lm=1, sc=1, rbf=1, fr=True, ps=padding, l=2, gu=1, gv=1, psc=0, su=1, ou=0, ov=0)
		# duplicate objects
		dups = cmds.duplicate(meshes)
		# if only one object, name it combined. For multiple objects combine all duplicates
		if len(dups) == 1:
			combined = cmds.rename(dups[0], combinedName)
		else:
			combined = cmds.polyUnite(dups, ch=True, mergeUVSets=True, centerPivot=True, name=combinedName)[0]
		# copy UVs from each mesh to the combined mesh
		for mesh in meshes:
			cmds.transferAttributes(mesh, combined, transferPositions=False, transferNormals=False, transferUVs=2, sampleSpace=4)
		# apply uv set
		cmds.polyUVSet(combined, currentUVSet=True, uvSet=uvSet)
		# remove combined mesh history
		cmds.delete(combined, constructionHistory=True)
		# delete any leftover groups from the original duplicates
		for dup in dups:
			try:
				if cmds.objExists(dup):
					cmds.delete(dup)
					parentGroup = cmds.listRelatives(dup, parent=True, fullPath=True)
					if parentGroup:
						children = cmds.listRelatives(parentGroup[0], children=True) or []
						if not children:
							cmds.delete(parentGroup[0])
			except:
				pass
		# add combined mesh to renderlayer
		cmds.select(combined, replace=True)
		cmds.editRenderLayerMembers(renderLayer, combined, noRecurse=True)
		# select combined geometry
		cmds.select(combined, replace=True)
		# render those lightmaps
		cmds.arnoldRenderToTexture(f=dirPath,uvs=uvSet,r=resolution,ee=True)
		# convert exr to tif
		shapeName = cmds.listRelatives(combined, shapes=True)[0]
		exrFilePath = os.path.join(dirPath, shapeName + ".exr")
		tifFilePath = os.path.join(dirPath, shapeName + ".tif")
		# check if a .tif file with the same name already exists and delete it if it does
		#if os.path.exists(tifFilePath):
		#	os.remove(tifFilePath)
		# run the conversion command for EXR to TIF
		subprocess.run(["magick",exrFilePath,"-define", "tiff:bits-per-sample=32","-compress", "none","-depth", "32",tifFilePath])
		# remove the exr file
		os.remove(exrFilePath)
		# return shape nodes, there should only be one
		shape = cmds.listRelatives(combined, shapes=True)
		# get object name from shape node
		exportName = combined
		if shape:
			exportName = shape[0]
		# remove combined mesh from render layer
		cmds.editRenderLayerMembers(renderLayer, combined, remove=True)
		# prep combined mesh for deletion
		cmds.editRenderLayerGlobals(currentRenderLayer='defaultRenderLayer')
		cmds.lockNode(combined, lock=False)
		# delete combined mesh
		cmds.delete(combined)
		# clear selection
		cmds.select(cl=True)
		return exportName

	'''Test for Cyril, and possible work in progress.'''
	def ExternalTextureHookup(self):
		if self.CheckIfRenderSetsExist():
			validationPass = self.ValidateRenderSets()

			if not validationPass:
				return

			notesAttr = cmds.getAttr(self.renderSetsName + '.notes')
			# hook up lightmap textures dict.
			hookUpLMTexturesDict = {}
			renderSets = eval(notesAttr)

			if not renderSets:
				return

			fileLoc = cmds.file(q=True, sn=True)
			currentFolder = os.path.dirname(fileLoc)
			textureFolder = os.path.dirname(currentFolder) + '/textures/LM/'
			# create textures folder
			if not os.path.exists(textureFolder):
				cmds.warning('The following path does not exist: ' + textureFolder)
				return

			for renderSet in renderSets:
				#pngName = prefix + renderSet + suffix
				pngName = renderSet
				pngLoc = textureFolder + pngName + '.png'

				if not os.path.exists(pngLoc):
					cmds.warning('The following texture does not exist: ' + pngLoc)
					continue

				hookUpLMTexturesDict.update({renderSet:{}})

				for mesh in self.renderSetsDict[renderSet]['objects']:
					hookUpLMTexturesDict[renderSet].setdefault(mesh, pngLoc)

			if hookUpLMTexturesDict:
				# Enable EuseLightmap if needed. #
				self.EnableUseLightmap(hookUpLMTexturesDict)
				# Because we need to give the enabled settings a moment to register. #
				cmds.pause(sec=5)
				# Hook up the lightmap png files back to the materials.
				self.HookUpLightMaps(hookUpLMTexturesDict)


	'''
	Set the PSD File Layer Blend Mode then Save and close if needed.
	layers = OrderedDict
	'''
	def ProcessPSDFile(self, psdFile, layers=OrderedDict(), tifFiles=[]):
		if layers and psdFile:
			try:
				psApp = comtypes.client.GetActiveObject('Photoshop.Application', dynamic=True)
			except:
				psApp = comtypes.client.CreateObject('Photoshop.Application', dynamic=True)
			try:
				psApp.DisplayDialogs = 3
			except:
				pass

			psd = psApp.Open(psdFile)
			doc = psApp.Application.ActiveDocument

			# Make the document 32-bits/channel
			s2t = psApp.StringIDToTypeID
			desc = comtypes.client.CreateObject('Photoshop.ActionDescriptor', dynamic=True)
			desc.putClass(s2t('to'), s2t('RGBColorMode'))
			desc.putInteger(s2t('depth'), 32)
			desc.putBoolean(s2t('merge'), False)
			psApp.ExecuteAction(s2t('convertMode'), desc, 3)
	
			maxRetries = 5

			for attempt in range(maxRetries):
				try:
					for index, layer in enumerate(doc.Layers):
						if layer.name in layers:
							if hasattr(layer, 'layers'):
								gamma_created = False
								for subLayer in layer.layers:
									# Convert the sub-layer to a smart object and link the file
									psApp.activeDocument.activeLayer = subLayer
									psApp.ExecuteAction(psApp.StringIDToTypeID('newPlacedLayer'), None, 3)
									desc3 = comtypes.client.CreateObject('Photoshop.ActionDescriptor', dynamic=True)
									desc3.putPath(psApp.CharIDToTypeID('null'), tifFiles[index])
									desc3.putInteger(psApp.CharIDToTypeID('PgNm'), 1)
									psApp.ExecuteAction(psApp.StringIDToTypeID('placedLayerRelinkToFile'), desc3, 3)

									# set layer blend mode
									if list(layers.items())[index][1] == 0:
										layer.blendMode = 11
										self.PrintMessage(layer.name + ' Photoshop blendMode set to Additive.')
									else:
										layer.blendMode = 5
										self.PrintMessage(layer.name + ' Photoshop blendMode set to Multiply.')

									# make sure the active layer is inside this folder
									if not gamma_created:
										try:
											if hasattr(layer, 'Layers') and layer.Layers.Count > 0:
												psApp.activeDocument.activeLayer = layer.Layers[1]
											elif hasattr(layer, 'artLayers') and layer.artLayers.Count > 0:
												psApp.activeDocument.activeLayer = layer.artLayers[1]
											else:
												psApp.activeDocument.activeLayer = layer
										except:
											psApp.activeDocument.activeLayer = layer

										# add gamma correction
										try:
											s2t = psApp.StringIDToTypeID
											makeDesc = comtypes.client.CreateObject('Photoshop.ActionDescriptor', dynamic=True)
											makeRef  = comtypes.client.CreateObject('Photoshop.ActionReference',  dynamic=True)
											makeRef.putClass(s2t('adjustmentLayer'))
											makeDesc.putReference(s2t('null'), makeRef)
											adjDesc  = comtypes.client.CreateObject('Photoshop.ActionDescriptor', dynamic=True)
											expsDesc = comtypes.client.CreateObject('Photoshop.ActionDescriptor', dynamic=True)
											expsDesc.putDouble(s2t('exposure'), 0.0)
											expsDesc.putDouble(s2t('offset'),   0.0)
											try:
												expsDesc.putDouble(s2t('gammaCorrection'), 0.4545)
											except:
												expsDesc.putDouble(s2t('gamma'), 0.4545)
											adjDesc.putObject(s2t('type'), s2t('exposure'), expsDesc)
											makeDesc.putObject(s2t('using'), s2t('adjustmentLayer'), adjDesc)
											psApp.ExecuteAction(s2t('make'), makeDesc, 3)
											psApp.ActiveDocument.ActiveLayer.Name = "Gamma Correction"
											gamma_created = True
										except Exception as e2:
											print(f"Could not add Gamma layer for {getattr(layer, 'name', '(unknown)')}: {e2}")

						elif layer.name == 'Background':
							try:
								# set Backgroundlayer to black.
								blackColor = comtypes.client.CreateObject('Photoshop.SolidColor', dynamic=True)
								blackColor.RGB.Red = 0
								blackColor.RGB.Green = 0
								blackColor.RGB.Blue = 0
								psApp.activeDocument.activeLayer = (psApp.activeDocument.artLayers['Background'])
								psApp.activeDocument.selection.selectAll()
								psApp.activeDocument.selection.Fill(blackColor)
							except:
								print('>>>> Could not set Background to Black!!! <<<<')
					break
				# add in a retry/delay if photoshop is busy
				except comtypes.COMError as e:
					if e.hresult == -2147417846 and attempt < maxRetries - 1:
						print(f"Photoshop is busy, retrying... (Attempt {attempt + 1}/{maxRetries})")
						time.sleep(2)
					else:
						raise

			doc.Save()
			psd.Close(1)
			#psApp.Quit()

			print(('*' * 20) + ' ProcessPSDFile has completed!!! ' + ('*' * 20))

	'''For printing a message with flare....'''
	def PrintMessage(self, text):
		print('')
		print('-=' * 40)
		print('=-' * 40)
		print(text)
		print('-=' * 40)
		print('=-' * 40)
		print('')
