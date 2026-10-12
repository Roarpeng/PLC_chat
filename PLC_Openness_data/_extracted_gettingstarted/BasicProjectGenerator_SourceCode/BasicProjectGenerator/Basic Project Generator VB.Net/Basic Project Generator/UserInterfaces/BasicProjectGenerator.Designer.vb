Namespace UserInterfaces
    Partial Class BasicProjectGenerator
        Inherits System.Windows.Forms.Form
        ''' <summary>
        ''' Required designer variable.
        ''' </summary>
        Private components As System.ComponentModel.IContainer = Nothing

        ''' <summary>
        ''' Clean up any resources being used.
        ''' </summary>
        ''' <paramname="disposing">true if managed resources should be disposed; otherwise, false.</param>
        Protected Overrides Sub Dispose(ByVal disposing As Boolean)
            If disposing AndAlso components IsNot Nothing Then
                components.Dispose()
            End If

            MyBase.Dispose(disposing)
        End Sub

#Region "Windows Form Designer generated code"

        ''' <summary>
        ''' Required method for Designer support - do not modify
        ''' the contents of this method with the code editor.
        ''' </summary>
        Private Sub InitializeComponent()
        Me.components = New System.ComponentModel.Container()
        Me.grb_TiaPortal = New System.Windows.Forms.GroupBox()
        Me.txb_CurrentProcessId = New System.Windows.Forms.TextBox()
        Me.lbl_CurrentProcessId = New System.Windows.Forms.Label()
        Me.lbl_Processes = New System.Windows.Forms.Label()
        Me.btn_ConnectTiaPortal = New System.Windows.Forms.Button()
        Me.cob_ProcessIds = New System.Windows.Forms.ComboBox()
        Me.label1 = New System.Windows.Forms.Label()
        Me.btn_CloseTiaPortal = New System.Windows.Forms.Button()
        Me.btn_OpenTiaPortal = New System.Windows.Forms.Button()
        Me.rdb_WithoutUI = New System.Windows.Forms.RadioButton()
        Me.rdb_WithUI = New System.Windows.Forms.RadioButton()
        Me.grb_TiaPortalProject = New System.Windows.Forms.GroupBox()
        Me.btn_CreateNewProject = New System.Windows.Forms.Button()
        Me.txb_TargetDirectory = New System.Windows.Forms.TextBox()
        Me.lbl_TargetDirectory = New System.Windows.Forms.Label()
        Me.txb_CurrentProjectName = New System.Windows.Forms.TextBox()
        Me.lbl_CurrentProjectName = New System.Windows.Forms.Label()
        Me.lbl_ProjectName = New System.Windows.Forms.Label()
        Me.txb_AvailableProjectName = New System.Windows.Forms.TextBox()
        Me.btn_CloseProject = New System.Windows.Forms.Button()
        Me.btn_SaveProject = New System.Windows.Forms.Button()
        Me.btn_LoadProject = New System.Windows.Forms.Button()
        Me.btn_OpenProject = New System.Windows.Forms.Button()
        Me.grb_AddNewDevice = New System.Windows.Forms.GroupBox()
        Me.txb_Station = New System.Windows.Forms.TextBox()
        Me.lab_Station = New System.Windows.Forms.Label()
        Me.ckb_IncludeFailsafe = New System.Windows.Forms.CheckBox()
        Me.lab_TypeIdentifier = New System.Windows.Forms.Label()
        Me.txb_TypeIdentifier = New System.Windows.Forms.TextBox()
        Me.txb_DeviceName = New System.Windows.Forms.TextBox()
        Me.lbl_DeviceName = New System.Windows.Forms.Label()
        Me.btn_AddNewDevice = New System.Windows.Forms.Button()
        Me.txb_Version = New System.Windows.Forms.TextBox()
        Me.txb_OrderNr = New System.Windows.Forms.TextBox()
        Me.lbl_Version = New System.Windows.Forms.Label()
        Me.lbl_OrderNr = New System.Windows.Forms.Label()
        Me.cob_DeviceTemplates = New System.Windows.Forms.ComboBox()
        Me.lbl_DeviceTemplates = New System.Windows.Forms.Label()
        Me.grb_Compile = New System.Windows.Forms.GroupBox()
        Me.lab_DeviceToCompile = New System.Windows.Forms.Label()
        Me.btn_CompileDevice = New System.Windows.Forms.Button()
        Me.cob_DeviceList = New System.Windows.Forms.ComboBox()
        Me.lib_DeviceList = New System.Windows.Forms.ListBox()
        Me.lab_DeviceList = New System.Windows.Forms.Label()
        Me.lib_TraceWriterOutput = New System.Windows.Forms.ListBox()
        Me.GeneratorToolTip = New System.Windows.Forms.ToolTip(Me.components)
        Me.grb_TiaPortal.SuspendLayout
        Me.grb_TiaPortalProject.SuspendLayout
        Me.grb_AddNewDevice.SuspendLayout
        Me.grb_Compile.SuspendLayout
        Me.SuspendLayout
        '
        'grb_TiaPortal
        '
        Me.grb_TiaPortal.Controls.Add(Me.txb_CurrentProcessId)
        Me.grb_TiaPortal.Controls.Add(Me.lbl_CurrentProcessId)
        Me.grb_TiaPortal.Controls.Add(Me.lbl_Processes)
        Me.grb_TiaPortal.Controls.Add(Me.btn_ConnectTiaPortal)
        Me.grb_TiaPortal.Controls.Add(Me.cob_ProcessIds)
        Me.grb_TiaPortal.Controls.Add(Me.label1)
        Me.grb_TiaPortal.Controls.Add(Me.btn_CloseTiaPortal)
        Me.grb_TiaPortal.Controls.Add(Me.btn_OpenTiaPortal)
        Me.grb_TiaPortal.Controls.Add(Me.rdb_WithoutUI)
        Me.grb_TiaPortal.Controls.Add(Me.rdb_WithUI)
        Me.grb_TiaPortal.Location = New System.Drawing.Point(12, 12)
        Me.grb_TiaPortal.Name = "grb_TiaPortal"
        Me.grb_TiaPortal.Size = New System.Drawing.Size(211, 436)
        Me.grb_TiaPortal.TabIndex = 0
        Me.grb_TiaPortal.TabStop = false
        Me.grb_TiaPortal.Text = "TIA Portal"
        '
        'txb_CurrentProcessId
        '
        Me.txb_CurrentProcessId.Location = New System.Drawing.Point(18, 130)
        Me.txb_CurrentProcessId.Name = "txb_CurrentProcessId"
        Me.txb_CurrentProcessId.ReadOnly = true
        Me.txb_CurrentProcessId.Size = New System.Drawing.Size(173, 20)
        Me.txb_CurrentProcessId.TabIndex = 4
        '
        'lbl_CurrentProcessId
        '
        Me.lbl_CurrentProcessId.AutoSize = true
        Me.lbl_CurrentProcessId.Location = New System.Drawing.Point(18, 115)
        Me.lbl_CurrentProcessId.Name = "lbl_CurrentProcessId"
        Me.lbl_CurrentProcessId.Size = New System.Drawing.Size(59, 13)
        Me.lbl_CurrentProcessId.TabIndex = 3
        Me.lbl_CurrentProcessId.Text = "Process ID"
        '
        'lbl_Processes
        '
        Me.lbl_Processes.AutoSize = true
        Me.lbl_Processes.Location = New System.Drawing.Point(18, 235)
        Me.lbl_Processes.Name = "lbl_Processes"
        Me.lbl_Processes.Size = New System.Drawing.Size(56, 13)
        Me.lbl_Processes.TabIndex = 6
        Me.lbl_Processes.Text = "Processes"
        '
        'btn_ConnectTiaPortal
        '
        Me.btn_ConnectTiaPortal.Location = New System.Drawing.Point(18, 289)
        Me.btn_ConnectTiaPortal.Name = "btn_ConnectTiaPortal"
        Me.btn_ConnectTiaPortal.Size = New System.Drawing.Size(173, 33)
        Me.btn_ConnectTiaPortal.TabIndex = 8
        Me.btn_ConnectTiaPortal.Text = "Connect TIA Portal"
        Me.btn_ConnectTiaPortal.UseVisualStyleBackColor = true
        '
        'cob_ProcessIds
        '
        Me.cob_ProcessIds.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList
        Me.cob_ProcessIds.FormattingEnabled = true
        Me.cob_ProcessIds.Location = New System.Drawing.Point(18, 250)
        Me.cob_ProcessIds.Name = "cob_ProcessIds"
        Me.cob_ProcessIds.Size = New System.Drawing.Size(173, 21)
        Me.cob_ProcessIds.TabIndex = 7
        '
        'label1
        '
        Me.label1.AutoSize = true
        Me.label1.Location = New System.Drawing.Point(23, 206)
        Me.label1.Name = "label1"
        Me.label1.Size = New System.Drawing.Size(0, 13)
        Me.label1.TabIndex = 5
        '
        'btn_CloseTiaPortal
        '
        Me.btn_CloseTiaPortal.Location = New System.Drawing.Point(21, 383)
        Me.btn_CloseTiaPortal.Name = "btn_CloseTiaPortal"
        Me.btn_CloseTiaPortal.Size = New System.Drawing.Size(170, 33)
        Me.btn_CloseTiaPortal.TabIndex = 9
        Me.btn_CloseTiaPortal.Text = "Close TIA Portal"
        Me.btn_CloseTiaPortal.UseVisualStyleBackColor = true
        '
        'btn_OpenTiaPortal
        '
        Me.btn_OpenTiaPortal.Location = New System.Drawing.Point(18, 71)
        Me.btn_OpenTiaPortal.Name = "btn_OpenTiaPortal"
        Me.btn_OpenTiaPortal.Size = New System.Drawing.Size(173, 33)
        Me.btn_OpenTiaPortal.TabIndex = 2
        Me.btn_OpenTiaPortal.Text = "Open TIA Portal"
        Me.btn_OpenTiaPortal.UseVisualStyleBackColor = true
        '
        'rdb_WithoutUI
        '
        Me.rdb_WithoutUI.AutoSize = true
        Me.rdb_WithoutUI.Location = New System.Drawing.Point(18, 48)
        Me.rdb_WithoutUI.Name = "rdb_WithoutUI"
        Me.rdb_WithoutUI.Size = New System.Drawing.Size(129, 17)
        Me.rdb_WithoutUI.TabIndex = 1
        Me.rdb_WithoutUI.TabStop = true
        Me.rdb_WithoutUI.Text = "Without user interface"
        Me.rdb_WithoutUI.UseVisualStyleBackColor = true
        '
        'rdb_WithUI
        '
        Me.rdb_WithUI.AutoSize = true
        Me.rdb_WithUI.Location = New System.Drawing.Point(18, 25)
        Me.rdb_WithUI.Name = "rdb_WithUI"
        Me.rdb_WithUI.Size = New System.Drawing.Size(114, 17)
        Me.rdb_WithUI.TabIndex = 0
        Me.rdb_WithUI.TabStop = true
        Me.rdb_WithUI.Text = "With user interface"
        Me.rdb_WithUI.UseVisualStyleBackColor = true
        '
        'grb_TiaPortalProject
        '
        Me.grb_TiaPortalProject.Controls.Add(Me.btn_CreateNewProject)
        Me.grb_TiaPortalProject.Controls.Add(Me.txb_TargetDirectory)
        Me.grb_TiaPortalProject.Controls.Add(Me.lbl_TargetDirectory)
        Me.grb_TiaPortalProject.Controls.Add(Me.txb_CurrentProjectName)
        Me.grb_TiaPortalProject.Controls.Add(Me.lbl_CurrentProjectName)
        Me.grb_TiaPortalProject.Controls.Add(Me.lbl_ProjectName)
        Me.grb_TiaPortalProject.Controls.Add(Me.txb_AvailableProjectName)
        Me.grb_TiaPortalProject.Controls.Add(Me.btn_CloseProject)
        Me.grb_TiaPortalProject.Controls.Add(Me.btn_SaveProject)
        Me.grb_TiaPortalProject.Controls.Add(Me.btn_LoadProject)
        Me.grb_TiaPortalProject.Controls.Add(Me.btn_OpenProject)
        Me.grb_TiaPortalProject.Location = New System.Drawing.Point(229, 12)
        Me.grb_TiaPortalProject.Name = "grb_TiaPortalProject"
        Me.grb_TiaPortalProject.Size = New System.Drawing.Size(211, 436)
        Me.grb_TiaPortalProject.TabIndex = 1
        Me.grb_TiaPortalProject.TabStop = false
        Me.grb_TiaPortalProject.Text = "TIA Portal project"
        '
        'btn_CreateNewProject
        '
        Me.btn_CreateNewProject.Location = New System.Drawing.Point(18, 32)
        Me.btn_CreateNewProject.Name = "btn_CreateNewProject"
        Me.btn_CreateNewProject.Size = New System.Drawing.Size(173, 33)
        Me.btn_CreateNewProject.TabIndex = 0
        Me.btn_CreateNewProject.Text = "Create new project"
        Me.btn_CreateNewProject.UseVisualStyleBackColor = true
        '
        'txb_TargetDirectory
        '
        Me.txb_TargetDirectory.Location = New System.Drawing.Point(18, 170)
        Me.txb_TargetDirectory.Name = "txb_TargetDirectory"
        Me.txb_TargetDirectory.ReadOnly = true
        Me.txb_TargetDirectory.Size = New System.Drawing.Size(173, 20)
        Me.txb_TargetDirectory.TabIndex = 5
        '
        'lbl_TargetDirectory
        '
        Me.lbl_TargetDirectory.AutoSize = true
        Me.lbl_TargetDirectory.Location = New System.Drawing.Point(18, 155)
        Me.lbl_TargetDirectory.Name = "lbl_TargetDirectory"
        Me.lbl_TargetDirectory.Size = New System.Drawing.Size(81, 13)
        Me.lbl_TargetDirectory.TabIndex = 4
        Me.lbl_TargetDirectory.Text = "Target directory"
        '
        'txb_CurrentProjectName
        '
        Me.txb_CurrentProjectName.Location = New System.Drawing.Point(18, 130)
        Me.txb_CurrentProjectName.Name = "txb_CurrentProjectName"
        Me.txb_CurrentProjectName.ReadOnly = true
        Me.txb_CurrentProjectName.Size = New System.Drawing.Size(173, 20)
        Me.txb_CurrentProjectName.TabIndex = 3
        '
        'lbl_CurrentProjectName
        '
        Me.lbl_CurrentProjectName.AutoSize = true
        Me.lbl_CurrentProjectName.Location = New System.Drawing.Point(18, 115)
        Me.lbl_CurrentProjectName.Name = "lbl_CurrentProjectName"
        Me.lbl_CurrentProjectName.Size = New System.Drawing.Size(69, 13)
        Me.lbl_CurrentProjectName.TabIndex = 2
        Me.lbl_CurrentProjectName.Text = "Project name"
        '
        'lbl_ProjectName
        '
        Me.lbl_ProjectName.AutoSize = true
        Me.lbl_ProjectName.Location = New System.Drawing.Point(18, 235)
        Me.lbl_ProjectName.Name = "lbl_ProjectName"
        Me.lbl_ProjectName.Size = New System.Drawing.Size(85, 13)
        Me.lbl_ProjectName.TabIndex = 6
        Me.lbl_ProjectName.Text = "Available project"
        '
        'txb_AvailableProjectName
        '
        Me.txb_AvailableProjectName.Location = New System.Drawing.Point(18, 250)
        Me.txb_AvailableProjectName.Name = "txb_AvailableProjectName"
        Me.txb_AvailableProjectName.ReadOnly = true
        Me.txb_AvailableProjectName.Size = New System.Drawing.Size(173, 20)
        Me.txb_AvailableProjectName.TabIndex = 7
        '
        'btn_CloseProject
        '
        Me.btn_CloseProject.Location = New System.Drawing.Point(18, 383)
        Me.btn_CloseProject.Name = "btn_CloseProject"
        Me.btn_CloseProject.Size = New System.Drawing.Size(173, 33)
        Me.btn_CloseProject.TabIndex = 10
        Me.btn_CloseProject.Text = "Close project"
        Me.btn_CloseProject.UseVisualStyleBackColor = true
        '
        'btn_SaveProject
        '
        Me.btn_SaveProject.Location = New System.Drawing.Point(18, 344)
        Me.btn_SaveProject.Name = "btn_SaveProject"
        Me.btn_SaveProject.Size = New System.Drawing.Size(173, 33)
        Me.btn_SaveProject.TabIndex = 9
        Me.btn_SaveProject.Text = "Save project"
        Me.btn_SaveProject.UseVisualStyleBackColor = true
        '
        'btn_LoadProject
        '
        Me.btn_LoadProject.Location = New System.Drawing.Point(18, 289)
        Me.btn_LoadProject.Name = "btn_LoadProject"
        Me.btn_LoadProject.Size = New System.Drawing.Size(173, 33)
        Me.btn_LoadProject.TabIndex = 8
        Me.btn_LoadProject.Text = "Load project"
        Me.btn_LoadProject.UseVisualStyleBackColor = true
        '
        'btn_OpenProject
        '
        Me.btn_OpenProject.Location = New System.Drawing.Point(18, 71)
        Me.btn_OpenProject.Name = "btn_OpenProject"
        Me.btn_OpenProject.Size = New System.Drawing.Size(173, 33)
        Me.btn_OpenProject.TabIndex = 1
        Me.btn_OpenProject.Text = "Open project"
        Me.btn_OpenProject.UseVisualStyleBackColor = true
        '
        'grb_AddNewDevice
        '
        Me.grb_AddNewDevice.Controls.Add(Me.txb_Station)
        Me.grb_AddNewDevice.Controls.Add(Me.lab_Station)
        Me.grb_AddNewDevice.Controls.Add(Me.ckb_IncludeFailsafe)
        Me.grb_AddNewDevice.Controls.Add(Me.lab_TypeIdentifier)
        Me.grb_AddNewDevice.Controls.Add(Me.txb_TypeIdentifier)
        Me.grb_AddNewDevice.Controls.Add(Me.txb_DeviceName)
        Me.grb_AddNewDevice.Controls.Add(Me.lbl_DeviceName)
        Me.grb_AddNewDevice.Controls.Add(Me.btn_AddNewDevice)
        Me.grb_AddNewDevice.Controls.Add(Me.txb_Version)
        Me.grb_AddNewDevice.Controls.Add(Me.txb_OrderNr)
        Me.grb_AddNewDevice.Controls.Add(Me.lbl_Version)
        Me.grb_AddNewDevice.Controls.Add(Me.lbl_OrderNr)
        Me.grb_AddNewDevice.Controls.Add(Me.cob_DeviceTemplates)
        Me.grb_AddNewDevice.Controls.Add(Me.lbl_DeviceTemplates)
        Me.grb_AddNewDevice.Location = New System.Drawing.Point(446, 12)
        Me.grb_AddNewDevice.Name = "grb_AddNewDevice"
        Me.grb_AddNewDevice.Size = New System.Drawing.Size(211, 436)
        Me.grb_AddNewDevice.TabIndex = 2
        Me.grb_AddNewDevice.TabStop = false
        Me.grb_AddNewDevice.Text = "Add new device"
        '
        'txb_Station
        '
        Me.txb_Station.Location = New System.Drawing.Point(18, 170)
        Me.txb_Station.Name = "txb_Station"
        Me.txb_Station.Size = New System.Drawing.Size(173, 20)
        Me.txb_Station.TabIndex = 6
        '
        'lab_Station
        '
        Me.lab_Station.AutoSize = true
        Me.lab_Station.Location = New System.Drawing.Point(18, 155)
        Me.lab_Station.Name = "lab_Station"
        Me.lab_Station.Size = New System.Drawing.Size(69, 13)
        Me.lab_Station.TabIndex = 5
        Me.lab_Station.Text = "Station name"
        '
        'ckb_IncludeFailsafe
        '
        Me.ckb_IncludeFailsafe.AutoSize = true
        Me.ckb_IncludeFailsafe.Location = New System.Drawing.Point(18, 87)
        Me.ckb_IncludeFailsafe.Name = "ckb_IncludeFailsafe"
        Me.ckb_IncludeFailsafe.Size = New System.Drawing.Size(100, 17)
        Me.ckb_IncludeFailsafe.TabIndex = 2
        Me.ckb_IncludeFailsafe.Text = "Include Failsafe"
        Me.ckb_IncludeFailsafe.UseVisualStyleBackColor = true
        '
        'lab_TypeIdentifier
        '
        Me.lab_TypeIdentifier.AutoSize = true
        Me.lab_TypeIdentifier.Location = New System.Drawing.Point(18, 275)
        Me.lab_TypeIdentifier.Name = "lab_TypeIdentifier"
        Me.lab_TypeIdentifier.Size = New System.Drawing.Size(73, 13)
        Me.lab_TypeIdentifier.TabIndex = 11
        Me.lab_TypeIdentifier.Text = "Type identifier"
        '
        'txb_TypeIdentifier
        '
        Me.txb_TypeIdentifier.Location = New System.Drawing.Point(18, 290)
        Me.txb_TypeIdentifier.Name = "txb_TypeIdentifier"
        Me.txb_TypeIdentifier.ReadOnly = true
        Me.txb_TypeIdentifier.Size = New System.Drawing.Size(173, 20)
        Me.txb_TypeIdentifier.TabIndex = 12
        '
        'txb_DeviceName
        '
        Me.txb_DeviceName.Location = New System.Drawing.Point(18, 130)
        Me.txb_DeviceName.Name = "txb_DeviceName"
        Me.txb_DeviceName.Size = New System.Drawing.Size(173, 20)
        Me.txb_DeviceName.TabIndex = 4
        '
        'lbl_DeviceName
        '
        Me.lbl_DeviceName.AutoSize = true
        Me.lbl_DeviceName.Location = New System.Drawing.Point(18, 115)
        Me.lbl_DeviceName.Name = "lbl_DeviceName"
        Me.lbl_DeviceName.Size = New System.Drawing.Size(70, 13)
        Me.lbl_DeviceName.TabIndex = 3
        Me.lbl_DeviceName.Text = "Device name"
        '
        'btn_AddNewDevice
        '
        Me.btn_AddNewDevice.Location = New System.Drawing.Point(18, 344)
        Me.btn_AddNewDevice.Name = "btn_AddNewDevice"
        Me.btn_AddNewDevice.Size = New System.Drawing.Size(173, 33)
        Me.btn_AddNewDevice.TabIndex = 13
        Me.btn_AddNewDevice.Text = "Add new device"
        Me.btn_AddNewDevice.UseVisualStyleBackColor = true
        '
        'txb_Version
        '
        Me.txb_Version.Location = New System.Drawing.Point(18, 250)
        Me.txb_Version.Name = "txb_Version"
        Me.txb_Version.Size = New System.Drawing.Size(173, 20)
        Me.txb_Version.TabIndex = 10
        '
        'txb_OrderNr
        '
        Me.txb_OrderNr.Location = New System.Drawing.Point(18, 210)
        Me.txb_OrderNr.Name = "txb_OrderNr"
        Me.txb_OrderNr.Size = New System.Drawing.Size(173, 20)
        Me.txb_OrderNr.TabIndex = 8
        '
        'lbl_Version
        '
        Me.lbl_Version.AutoSize = true
        Me.lbl_Version.Location = New System.Drawing.Point(18, 235)
        Me.lbl_Version.Name = "lbl_Version"
        Me.lbl_Version.Size = New System.Drawing.Size(42, 13)
        Me.lbl_Version.TabIndex = 9
        Me.lbl_Version.Text = "Version"
        '
        'lbl_OrderNr
        '
        Me.lbl_OrderNr.AutoSize = true
        Me.lbl_OrderNr.Location = New System.Drawing.Point(18, 195)
        Me.lbl_OrderNr.Name = "lbl_OrderNr"
        Me.lbl_OrderNr.Size = New System.Drawing.Size(71, 13)
        Me.lbl_OrderNr.TabIndex = 7
        Me.lbl_OrderNr.Text = "Order number"
        '
        'cob_DeviceTemplates
        '
        Me.cob_DeviceTemplates.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList
        Me.cob_DeviceTemplates.FormattingEnabled = true
        Me.cob_DeviceTemplates.Location = New System.Drawing.Point(18, 44)
        Me.cob_DeviceTemplates.Name = "cob_DeviceTemplates"
        Me.cob_DeviceTemplates.Size = New System.Drawing.Size(173, 21)
        Me.cob_DeviceTemplates.TabIndex = 1
        '
        'lbl_DeviceTemplates
        '
        Me.lbl_DeviceTemplates.AutoSize = true
        Me.lbl_DeviceTemplates.Location = New System.Drawing.Point(15, 27)
        Me.lbl_DeviceTemplates.Name = "lbl_DeviceTemplates"
        Me.lbl_DeviceTemplates.Size = New System.Drawing.Size(89, 13)
        Me.lbl_DeviceTemplates.TabIndex = 0
        Me.lbl_DeviceTemplates.Text = "Device templates"
        '
        'grb_Compile
        '
        Me.grb_Compile.Controls.Add(Me.lab_DeviceToCompile)
        Me.grb_Compile.Controls.Add(Me.btn_CompileDevice)
        Me.grb_Compile.Controls.Add(Me.cob_DeviceList)
        Me.grb_Compile.Controls.Add(Me.lib_DeviceList)
        Me.grb_Compile.Controls.Add(Me.lab_DeviceList)
        Me.grb_Compile.Location = New System.Drawing.Point(663, 12)
        Me.grb_Compile.Name = "grb_Compile"
        Me.grb_Compile.Size = New System.Drawing.Size(211, 436)
        Me.grb_Compile.TabIndex = 3
        Me.grb_Compile.TabStop = false
        Me.grb_Compile.Text = "Compile"
        '
        'lab_DeviceToCompile
        '
        Me.lab_DeviceToCompile.AutoSize = true
        Me.lab_DeviceToCompile.Location = New System.Drawing.Point(15, 235)
        Me.lab_DeviceToCompile.Name = "lab_DeviceToCompile"
        Me.lab_DeviceToCompile.Size = New System.Drawing.Size(92, 13)
        Me.lab_DeviceToCompile.TabIndex = 2
        Me.lab_DeviceToCompile.Text = "Device to compile"
        '
        'btn_CompileDevice
        '
        Me.btn_CompileDevice.Location = New System.Drawing.Point(18, 289)
        Me.btn_CompileDevice.Name = "btn_CompileDevice"
        Me.btn_CompileDevice.Size = New System.Drawing.Size(173, 33)
        Me.btn_CompileDevice.TabIndex = 4
        Me.btn_CompileDevice.Text = "Compile device"
        Me.btn_CompileDevice.UseVisualStyleBackColor = true
        '
        'cob_DeviceList
        '
        Me.cob_DeviceList.DropDownStyle = System.Windows.Forms.ComboBoxStyle.DropDownList
        Me.cob_DeviceList.FormattingEnabled = true
        Me.cob_DeviceList.Location = New System.Drawing.Point(18, 250)
        Me.cob_DeviceList.Name = "cob_DeviceList"
        Me.cob_DeviceList.Size = New System.Drawing.Size(173, 21)
        Me.cob_DeviceList.TabIndex = 3
        '
        'lib_DeviceList
        '
        Me.lib_DeviceList.FormattingEnabled = true
        Me.lib_DeviceList.HorizontalExtent = 200
        Me.lib_DeviceList.HorizontalScrollbar = true
        Me.lib_DeviceList.Location = New System.Drawing.Point(18, 43)
        Me.lib_DeviceList.Name = "lib_DeviceList"
        Me.lib_DeviceList.SelectionMode = System.Windows.Forms.SelectionMode.None
        Me.lib_DeviceList.Size = New System.Drawing.Size(173, 186)
        Me.lib_DeviceList.TabIndex = 1
        '
        'lab_DeviceList
        '
        Me.lab_DeviceList.AutoSize = true
        Me.lab_DeviceList.Location = New System.Drawing.Point(15, 27)
        Me.lab_DeviceList.Name = "lab_DeviceList"
        Me.lab_DeviceList.Size = New System.Drawing.Size(56, 13)
        Me.lab_DeviceList.TabIndex = 0
        Me.lab_DeviceList.Text = "Device list"
        '
        'lib_TraceWriterOutput
        '
        Me.lib_TraceWriterOutput.FormattingEnabled = true
        Me.lib_TraceWriterOutput.HorizontalScrollbar = true
        Me.lib_TraceWriterOutput.Location = New System.Drawing.Point(12, 454)
        Me.lib_TraceWriterOutput.Name = "lib_TraceWriterOutput"
        Me.lib_TraceWriterOutput.Size = New System.Drawing.Size(862, 121)
        Me.lib_TraceWriterOutput.TabIndex = 4
        '
        'BasicProjectGenerator
        '
        Me.AutoScaleDimensions = New System.Drawing.SizeF(6!, 13!)
        Me.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font
        Me.AutoScroll = true
        Me.ClientSize = New System.Drawing.Size(887, 588)
        Me.Controls.Add(Me.lib_TraceWriterOutput)
        Me.Controls.Add(Me.grb_Compile)
        Me.Controls.Add(Me.grb_AddNewDevice)
        Me.Controls.Add(Me.grb_TiaPortalProject)
        Me.Controls.Add(Me.grb_TiaPortal)
        Me.MinimumSize = New System.Drawing.Size(250, 300)
        Me.Name = "BasicProjectGenerator"
        Me.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen
        Me.Text = "Basic Project Generator"
        Me.grb_TiaPortal.ResumeLayout(false)
        Me.grb_TiaPortal.PerformLayout
        Me.grb_TiaPortalProject.ResumeLayout(false)
        Me.grb_TiaPortalProject.PerformLayout
        Me.grb_AddNewDevice.ResumeLayout(false)
        Me.grb_AddNewDevice.PerformLayout
        Me.grb_Compile.ResumeLayout(false)
        Me.grb_Compile.PerformLayout
        Me.ResumeLayout(false)

End Sub

#End Region

        Private WithEvents grb_TiaPortal As System.Windows.Forms.GroupBox
        Private WithEvents btn_CloseTiaPortal As System.Windows.Forms.Button
        Private WithEvents btn_OpenTiaPortal As System.Windows.Forms.Button
        Private WithEvents rdb_WithoutUI As System.Windows.Forms.RadioButton
        Private WithEvents rdb_WithUI As System.Windows.Forms.RadioButton
        Private WithEvents grb_TiaPortalProject As System.Windows.Forms.GroupBox
        Private WithEvents grb_AddNewDevice As System.Windows.Forms.GroupBox
        Private WithEvents grb_Compile As System.Windows.Forms.GroupBox
        Private WithEvents label1 As System.Windows.Forms.Label
        Private WithEvents lbl_Processes As System.Windows.Forms.Label
        Private WithEvents btn_ConnectTiaPortal As System.Windows.Forms.Button
        Private WithEvents cob_ProcessIds As System.Windows.Forms.ComboBox
        Private WithEvents lbl_CurrentProcessId As System.Windows.Forms.Label
        Private WithEvents lib_TraceWriterOutput As System.Windows.Forms.ListBox
        Private WithEvents txb_CurrentProcessId As System.Windows.Forms.TextBox
        Private WithEvents txb_CurrentProjectName As System.Windows.Forms.TextBox
        Private WithEvents lbl_CurrentProjectName As System.Windows.Forms.Label
        Private WithEvents lbl_ProjectName As System.Windows.Forms.Label
        Private WithEvents txb_AvailableProjectName As System.Windows.Forms.TextBox
        Private WithEvents btn_CloseProject As System.Windows.Forms.Button
        Private WithEvents btn_SaveProject As System.Windows.Forms.Button
        Private WithEvents btn_LoadProject As System.Windows.Forms.Button
        Private WithEvents btn_OpenProject As System.Windows.Forms.Button
        Private WithEvents cob_DeviceTemplates As System.Windows.Forms.ComboBox
        Private WithEvents lbl_DeviceTemplates As System.Windows.Forms.Label
        Private WithEvents txb_DeviceName As System.Windows.Forms.TextBox
        Private WithEvents lbl_DeviceName As System.Windows.Forms.Label
        Private WithEvents btn_AddNewDevice As System.Windows.Forms.Button
        Private WithEvents txb_Version As System.Windows.Forms.TextBox
        Private WithEvents txb_OrderNr As System.Windows.Forms.TextBox
        Private WithEvents lbl_Version As System.Windows.Forms.Label
        Private WithEvents lbl_OrderNr As System.Windows.Forms.Label
        Private WithEvents lab_DeviceList As System.Windows.Forms.Label
        Private WithEvents btn_CreateNewProject As System.Windows.Forms.Button
        Private WithEvents txb_TargetDirectory As System.Windows.Forms.TextBox
        Private WithEvents lbl_TargetDirectory As System.Windows.Forms.Label
        Private WithEvents GeneratorToolTip As System.Windows.Forms.ToolTip
        Private WithEvents lab_TypeIdentifier As System.Windows.Forms.Label
        Private WithEvents txb_TypeIdentifier As System.Windows.Forms.TextBox
        Private WithEvents lib_DeviceList As System.Windows.Forms.ListBox
        Private WithEvents ckb_IncludeFailsafe As System.Windows.Forms.CheckBox
        Private WithEvents txb_Station As System.Windows.Forms.TextBox
        Private WithEvents lab_Station As System.Windows.Forms.Label
        Private WithEvents cob_DeviceList As System.Windows.Forms.ComboBox
        Private WithEvents btn_CompileDevice As System.Windows.Forms.Button
        Private WithEvents lab_DeviceToCompile As System.Windows.Forms.Label
    End Class
End Namespace
