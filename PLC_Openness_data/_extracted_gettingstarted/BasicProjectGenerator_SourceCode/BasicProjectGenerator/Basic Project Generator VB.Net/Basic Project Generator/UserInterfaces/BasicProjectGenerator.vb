Imports System
Imports System.Collections.Generic
Imports System.Linq
Imports System.Runtime.CompilerServices
Imports System.Windows.Forms
Imports Basic_Project_Generator.Interfaces
Imports Basic_Project_Generator.Models
Imports Basic_Project_Generator.Services
Imports Siemens.Engineering

Namespace UserInterfaces
    ''' <summary>
    ''' The main application form
    ''' </summary>
    Public Class BasicProjectGenerator
#Region "fields"

        Private Shared _apiWrapper As ApiWrapper
        Private ReadOnly _projectGeneratorService As ProjectGeneratorService
        Private ReadOnly _traceWriter As TraceWriter

#End Region

#Region "ctor"

        Public Sub New(<CallerMemberName> Optional caller As String = "")
            InitializeComponent()

            _traceWriter = New TraceWriter(lib_TraceWriterOutput)
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name & " called from " & caller & Microsoft.VisualBasic.Constants.vbLf)

            _apiWrapper = New ApiWrapper(_traceWriter)

            _projectGeneratorService = New ProjectGeneratorService(_traceWriter, _apiWrapper)

            ManageUiState()
        End Sub

#End Region

#Region "methods"

#Region "BasicProjectGenerator"

        ''' <summary>
        ''' Initialization of controls
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub BasicProjectGenerator_Load(sender As Object, e As EventArgs) Handles MyBase.Load
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            AddRadioCheckedBinding(rdb_WithoutUI, _apiWrapper, NameOf(_apiWrapper.TiaPortalMode), TiaPortalMode.WithoutUserInterface)
            AddRadioCheckedBinding(rdb_WithUI, _apiWrapper, NameOf(_apiWrapper.TiaPortalMode), TiaPortalMode.WithUserInterface)

            _apiWrapper.TiaPortalMode = TiaPortalMode.WithUserInterface

            cob_DeviceList.ValueMember = _projectGeneratorService.DeviceModel.GetDeviceNamePropertyName()
            cob_DeviceList.Text = _projectGeneratorService.DeviceModel.GetNamePropertyName()

            GeneratorToolTip = New ToolTip With {
                .AutoPopDelay = 5000,
                .InitialDelay = 1000,
                .ReshowDelay = 500,
                .ShowAlways = False
            }
        End Sub

        ''' <summary>
        ''' Add a property binding to radio button
        ''' </summary>
        ''' <typeparamname="T"></typeparam>
        ''' <paramname="radio"></param>
        ''' <paramname="dataSource"></param>
        ''' <paramname="dataMember"></param>
        ''' <paramname="trueValue"></param>
        Private Sub AddRadioCheckedBinding(Of T)(radio As RadioButton, dataSource As Object, dataMember As String, trueValue As T)
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim binding = New Binding(NameOf(RadioButton.Checked), dataSource, dataMember, True, DataSourceUpdateMode.OnPropertyChanged)
            AddHandler binding.Parse,
                Sub(s, a)
                    If CBool(a.Value) Then a.Value = trueValue
                End Sub
            AddHandler binding.Format,
                Sub(s, a)
                    a.Value = a.Value.Equals(trueValue)
                End Sub
            radio.DataBindings.Add(binding)
        End Sub

        ''' <summary>
        ''' Retrieve the selected index and item
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub Cob_ProcessIds_SelectedIndexChanged(sender As Object, e As EventArgs) Handles cob_ProcessIds.SelectedIndexChanged
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            _projectGeneratorService.SelectedProcessIndex = cob_ProcessIds.SelectedIndex
            _projectGeneratorService.SelectedProcessItem = cob_ProcessIds.SelectedItem.ToString()

            UpdateProcessUiState()
        End Sub

        ''' <summary>
        ''' Manage the UI state
        ''' </summary>
        Private Sub ManageUiState()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            UpdateProcessList()
            UpdateProcessUiState()
            UpdateProjectUiState()
            UpdateDeviceUiState()
            UpdateCompileUiState()
        End Sub

        ''' <summary>
        ''' Manage process list changes
        ''' </summary>
        Private Sub UpdateProcessList()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            cob_ProcessIds.Items.Clear()
            cob_ProcessIds.ResetText()

            Dim processIds As IList(Of String) = _projectGeneratorService.GetTiaPortalProcesses()
            If processIds IsNot Nothing AndAlso processIds.Count > 0 Then
                For Each item In processIds
                    cob_ProcessIds.Items.Add(item)
                Next

                Dim index As Integer = cob_ProcessIds.FindString($"ID {_projectGeneratorService.GetCurrentTiaProcessId()}")
                cob_ProcessIds.SelectedIndex = index
            End If
        End Sub

        ''' <summary>
        ''' Manage controls for the TIA Portal process region
        ''' </summary>
        Private Sub UpdateProcessUiState()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim currentProcessId = _projectGeneratorService.GetCurrentTiaProcessId()
            txb_CurrentProcessId.Text = currentProcessId
            Dim availableProcessId = _projectGeneratorService.GetSelectedProcessIdAsString()

            rdb_WithUI.Enabled = String.IsNullOrEmpty(currentProcessId)
            rdb_WithoutUI.Enabled = String.IsNullOrEmpty(currentProcessId)
            btn_OpenTiaPortal.Enabled = String.IsNullOrEmpty(currentProcessId)
            txb_CurrentProcessId.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            cob_ProcessIds.Enabled = cob_ProcessIds.Items.Count > 0
            btn_ConnectTiaPortal.Enabled = cob_ProcessIds.Items.Count > 0 AndAlso (cob_ProcessIds.SelectedIndex > -1 AndAlso String.IsNullOrEmpty(currentProcessId) OrElse Not Equals(currentProcessId, availableProcessId))
            btn_CloseTiaPortal.Enabled = Not String.IsNullOrEmpty(currentProcessId)
        End Sub

        ''' <summary>
        ''' Manage controls for the project region
        ''' </summary>
        Private Sub UpdateProjectUiState()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            txb_CurrentProjectName.Text = _projectGeneratorService.GetCurrentProjectName()
            txb_TargetDirectory.Text = _projectGeneratorService.GetTargetDirectory()
            txb_AvailableProjectName.Text = _projectGeneratorService.GetAvailableProject()

            Dim currentProcessId = _projectGeneratorService.GetCurrentTiaProcessId()
            btn_CreateNewProject.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            btn_OpenProject.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            txb_CurrentProjectName.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            txb_TargetDirectory.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            txb_AvailableProjectName.Enabled = Not String.IsNullOrEmpty(currentProcessId)
            btn_LoadProject.Enabled = String.IsNullOrEmpty(txb_CurrentProjectName.Text) AndAlso Not String.IsNullOrEmpty(txb_AvailableProjectName.Text)
            btn_SaveProject.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text) AndAlso _apiWrapper.CurrentProject.IsModified
            btn_CloseProject.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)

            If Not String.IsNullOrEmpty(txb_CurrentProjectName.Text) Then
                GetCurrentDeviceCount()
                LoadDeviceCatalog()
            End If
        End Sub

        ''' <summary>
        ''' Manage controls for the device region
        ''' </summary>
        Private Sub UpdateDeviceUiState()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            cob_DeviceTemplates.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            ckb_IncludeFailsafe.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            txb_DeviceName.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            txb_Station.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            txb_TypeIdentifier.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            txb_OrderNr.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            txb_Version.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
            btn_AddNewDevice.Enabled = Not String.IsNullOrEmpty(txb_CurrentProjectName.Text)
        End Sub

        ''' <summary>
        ''' Manage controls for the compile region
        ''' </summary>
        Private Sub UpdateCompileUiState()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            cob_DeviceList.Enabled = cob_DeviceList.Items.Count > 0
            lib_DeviceList.Enabled = cob_DeviceList.Items.Count > 0
            btn_CompileDevice.Enabled = cob_DeviceList.Items.Count > 0
        End Sub

        Private Sub txb_CurrentProcessId_MouseHover(sender As Object, e As EventArgs) Handles txb_CurrentProcessId.MouseHover
            GeneratorToolTip.SetToolTip(txb_CurrentProcessId, txb_CurrentProcessId.Text)
        End Sub

        Private Sub txb_TargetDirectory_MouseHover(sender As Object, e As EventArgs) Handles txb_TargetDirectory.MouseHover
            GeneratorToolTip.SetToolTip(txb_TargetDirectory, txb_TargetDirectory.Text)
        End Sub

        Private Sub txb_CurrentProjectName_MouseHover(sender As Object, e As EventArgs) Handles txb_CurrentProjectName.MouseHover
            GeneratorToolTip.SetToolTip(txb_CurrentProjectName, txb_CurrentProjectName.Text)
        End Sub

        Private Sub txb_AvailableProjectName_MouseHover(sender As Object, e As EventArgs) Handles txb_AvailableProjectName.MouseHover
            GeneratorToolTip.SetToolTip(txb_AvailableProjectName, txb_AvailableProjectName.Text)
        End Sub

        Private Sub txb_Station_MouseHover(sender As Object, e As EventArgs) Handles txb_Station.MouseHover
            GeneratorToolTip.SetToolTip(txb_Station, txb_Station.Text)
        End Sub

        Private Sub txb_DeviceName_MouseHover(sender As Object, e As EventArgs) Handles txb_DeviceName.MouseHover
            GeneratorToolTip.SetToolTip(txb_DeviceName, txb_DeviceName.Text)
        End Sub

        Private Sub txb_TypeIdentifier_MouseHover(sender As Object, e As EventArgs) Handles txb_TypeIdentifier.MouseHover
            GeneratorToolTip.SetToolTip(txb_TypeIdentifier, txb_TypeIdentifier.Text)
        End Sub

        Private Sub txb_OrderNr_MouseHover(sender As Object, e As EventArgs) Handles txb_OrderNr.MouseHover
            GeneratorToolTip.SetToolTip(txb_OrderNr, txb_OrderNr.Text)
        End Sub

        Private Sub txb_Version_MouseHover(sender As Object, e As EventArgs) Handles txb_Version.MouseHover
            GeneratorToolTip.SetToolTip(txb_Version, txb_Version.Text)
        End Sub

        Private Sub txb_OrderNr_Leave(sender As Object, e As EventArgs) Handles txb_OrderNr.Leave
            txb_TypeIdentifier.Text = "OrderNumber:" & txb_OrderNr.Text & "/" & txb_Version.Text
        End Sub

        Private Sub txb_Version_Leave(sender As Object, e As EventArgs) Handles txb_Version.Leave
            txb_TypeIdentifier.Text = "OrderNumber:" & txb_OrderNr.Text & "/" & txb_Version.Text
        End Sub

#End Region

#Region "TIA Portal"

        ''' <summary>
        ''' Open a TIA Portal instance
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_OpenTiaPortal_Click(sender As Object, e As EventArgs) Handles btn_OpenTiaPortal.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Cursor.Current = Cursors.WaitCursor

            _projectGeneratorService.OpenTiaPortal()

            ResetDeviceList()
            ResetDeviceCatalog()

            ManageUiState()

            Cursor.Current = Cursors.Default
        End Sub

        ''' <summary>
        ''' Connect to a open TIA Portal instance
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_ConnectTiaPortal_Click(sender As Object, e As EventArgs) Handles btn_ConnectTiaPortal.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim canConnectToTiaPortal As Boolean = CheckProjectModified()

            Dim processId As Integer = _projectGeneratorService.GetSelectedProcessId()

            If canConnectToTiaPortal AndAlso processId <> -1 Then
                CloseProject()

                Cursor.Current = Cursors.WaitCursor

                _projectGeneratorService.ConnectTiaPortal(processId)

                ManageUiState()

                Cursor.Current = Cursors.Default
            End If
        End Sub

        ''' <summary>
        ''' Close a TIA Portal instance
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_CloseTiaPortal_Click(sender As Object, e As EventArgs) Handles btn_CloseTiaPortal.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim canCloseTiaPortal As Boolean = CheckProjectModified()

            If canCloseTiaPortal Then
                CloseProject()
                ResetDeviceList()
                ResetDeviceCatalog()

                _projectGeneratorService.CloseTiaPortal()

                ManageUiState()
            End If
        End Sub

#End Region

#Region "TIA Portal Project"

        ''' <summary>
        ''' Create a new project
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_CreateNewProject_Click(sender As Object, e As EventArgs) Handles btn_CreateNewProject.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim canCreateProject = True

            If Not String.IsNullOrEmpty(_projectGeneratorService.GetCurrentProjectName()) Then
                canCreateProject = CheckProjectModified()
            End If

            If canCreateProject Then
                CloseProject()

                Cursor.Current = Cursors.WaitCursor

                _projectGeneratorService.CreateNewProject()

                ManageUiState()

                Cursor.Current = Cursors.Default
            End If
        End Sub

        ''' <summary>
        ''' Open a selected project
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_OpenProject_Click(sender As Object, e As EventArgs) Handles btn_OpenProject.Click
            Try
                Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
                _traceWriter.Write(methodBase.Name)

                Dim canOpenProject = True

                If Not String.IsNullOrEmpty(_projectGeneratorService.GetCurrentProjectName()) Then
                    canOpenProject = CheckProjectModified()
                End If

                If canOpenProject Then
                    CloseProject()

                    Cursor.Current = Cursors.WaitCursor

                    _projectGeneratorService.OpenProject()

                    ManageUiState()

                    Cursor.Current = Cursors.Default
                End If
            Catch exception As Exception
                _traceWriter.Write(exception.Message)
            End Try
        End Sub

        ''' <summary>
        ''' Load a open project from connected instance -> see 'DoConnectTiaPortal'
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_LoadProject_Click(sender As Object, e As EventArgs) Handles btn_LoadProject.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Cursor.Current = Cursors.WaitCursor

            _projectGeneratorService.LoadProject()

            ManageUiState()

            Cursor.Current = Cursors.Default
        End Sub

        ''' <summary>
        ''' Save the project
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_SaveProject_Click(sender As Object, e As EventArgs) Handles btn_SaveProject.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Cursor.Current = Cursors.WaitCursor

            _projectGeneratorService.SaveProject()

            ManageUiState()

            Cursor.Current = Cursors.Default
        End Sub

        ''' <summary>
        ''' Check for changes and close the project
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_CloseProject_Click(sender As Object, e As EventArgs) Handles btn_CloseProject.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim close As Boolean = CheckProjectModified()

            If close Then
                CloseProject()
            End If
        End Sub

        ''' <summary>
        ''' Close the project and reset details
        ''' </summary>
        Private Sub CloseProject()
            _projectGeneratorService.CloseProject()

            ResetDeviceList()
            ResetDeviceCatalog()

            ManageUiState()
        End Sub

        ''' <summary>
        ''' Check for project changes
        ''' </summary>
        ''' <returns></returns>
        Private Function CheckProjectModified() As Boolean
            Dim projectSaved = True

            If _apiWrapper.CurrentProject IsNot Nothing AndAlso _apiWrapper.CurrentProject.IsModified Then
                projectSaved = False
                Dim result = MessageBox.Show("Do you want to save the changes to the current project?", "Project has been modified", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Warning)

                If result = DialogResult.Yes OrElse result = DialogResult.No Then
                    projectSaved = True

                    If result = DialogResult.Yes Then
                        _projectGeneratorService.SaveProject()
                    End If
                Else
                    _traceWriter.Write("Close project was canceled!")
                End If
            End If

            Return projectSaved
        End Function

#End Region

#Region "Device"

        ''' <summary>
        ''' Load the template catalog for new devices from xml.
        ''' If th catalog is changed, the current project should be close and reopened
        ''' to reload the catalog changes.
        ''' </summary>
        Private Sub LoadDeviceCatalog()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            If _projectGeneratorService.LoadDeviceCatalog() Then
                If _projectGeneratorService.DeviceModel.DeviceCatalog.DeviceItemComposition.Count > 0 Then
                    cob_DeviceTemplates.Items.Clear()
                    cob_DeviceTemplates.ResetText()
                End If

                For Each device In _projectGeneratorService.DeviceModel.DeviceCatalog.DeviceItemComposition
                    cob_DeviceTemplates.Items.Add(device.TemplateName)
                Next

                If cob_DeviceTemplates.Items.Count > 0 Then
                    cob_DeviceTemplates.SelectedIndex = 0
                End If
            End If
        End Sub

        ''' <summary>
        ''' Retrieve the device count from project
        ''' </summary>
        Private Sub GetCurrentDeviceCount()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            _projectGeneratorService.DeviceModel.CurrentDeviceCount = _apiWrapper.CurrentProject.Devices.Count

            ResetDeviceList()

            _projectGeneratorService.GetCurrentDeviceList()

            For Each item In _projectGeneratorService.DeviceModel.DeviceItemComposition
                cob_DeviceList.Items.Add(item)
            Next

            If cob_DeviceList.Items.Count > 0 Then
                cob_DeviceList.SelectedIndex = 0
            End If

            ' Get device name for listbox
            For Each device In _apiWrapper.CurrentProject.Devices
                lib_DeviceList.Items.Add(device.Name)
            Next
        End Sub

        ''' <summary>
        ''' Update the UI with new Information if the selected device template has been changed
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cob_DeviceTemplates_SelectedIndexChanged(sender As Object, e As EventArgs) Handles cob_DeviceTemplates.SelectedIndexChanged
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            If _projectGeneratorService.DeviceCatalogLoaded Then
                Dim deviceItem =
                    (From device In _projectGeneratorService.DeviceModel.DeviceCatalog.DeviceItemComposition
                     Where Equals(device.TemplateName, cob_DeviceTemplates.SelectedItem.ToString())
                     Select device).FirstOrDefault()

                If deviceItem IsNot Nothing Then
                    _projectGeneratorService.NewDevice = New Device With {
                        .Station = deviceItem.Station,
                        .TemplateName = deviceItem.TemplateName,
                        .DeviceName = deviceItem.DeviceName,
                        .OrderNumber = deviceItem.OrderNumber,
                        .FirmwareVersion = deviceItem.FirmwareVersion,
                        .IncludeFailsafe = deviceItem.IncludeFailsafe,
                        .PositionNumber = _projectGeneratorService.DeviceModel.CurrentDeviceCount
                    }

                    ckb_IncludeFailsafe.Checked = _projectGeneratorService.NewDevice.IncludeFailsafe
                    txb_DeviceName.Text = _projectGeneratorService.NewDevice.DeviceName & "_" & (_projectGeneratorService.DeviceModel.CurrentDeviceCount + 1).ToString()
                    txb_Station.Text = _projectGeneratorService.NewDevice.Station
                    txb_TypeIdentifier.Text = _projectGeneratorService.NewDevice.TypeIdentifier
                    txb_OrderNr.Text = _projectGeneratorService.NewDevice.OrderNumber
                    txb_Version.Text = _projectGeneratorService.NewDevice.FirmwareVersion
                End If
            End If
        End Sub

        ''' <summary>
        ''' Reset the device list
        ''' </summary>
        Private Sub ResetDeviceList()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            cob_DeviceList.Items.Clear()
            cob_DeviceList.ResetText()

            lib_DeviceList.Items.Clear()
            lib_DeviceList.ResetText()
        End Sub

        ''' <summary>
        ''' Reset the device catalog (device template list)
        ''' </summary>
        Private Sub ResetDeviceCatalog()
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            cob_DeviceTemplates.Items.Clear()
            cob_DeviceTemplates.ResetText()

            ckb_IncludeFailsafe.Checked = False

            txb_DeviceName.Text = String.Empty
            txb_Station.Text = String.Empty
            txb_TypeIdentifier.Text = String.Empty
            txb_OrderNr.Text = String.Empty
            txb_Version.Text = String.Empty
        End Sub

        ''' <summary>
        ''' Retrieve a new device and add it to the project
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_AddNewDevice_Click(sender As Object, e As EventArgs) Handles btn_AddNewDevice.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Try
                If GetNewDevice() Then
                    Cursor.Current = Cursors.WaitCursor

                    _projectGeneratorService.AddNewDevice(_projectGeneratorService.NewDevice)

                    Cursor.Current = Cursors.Default

                    _projectGeneratorService.SetPlcSecuritySettings(_projectGeneratorService.NewDevice.Name, _projectGeneratorService.NewDevice.IncludeFailsafe)

                    GetCurrentDeviceCount()

                    ManageUiState()
                Else
                    _traceWriter.Write("Error: New device object could not be created.")
                    MessageBox.Show("The properties device name, station, order number and version are required!", "Error create a new device", MessageBoxButtons.OK, MessageBoxIcon.Information)
                End If
            Catch exception As Exception
                _traceWriter.Write(exception.Message)
            End Try
        End Sub

        ''' <summary>
        ''' Create a new device object
        ''' </summary>
        ''' <returns></returns>
        Private Function GetNewDevice() As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Dim result = False

            Try
                If _projectGeneratorService.NewDevice IsNot Nothing Then
                    _projectGeneratorService.NewDevice.Station = txb_Station.Text
                    _projectGeneratorService.NewDevice.DeviceName = txb_DeviceName.Text
                    _projectGeneratorService.NewDevice.OrderNumber = txb_OrderNr.Text
                    _projectGeneratorService.NewDevice.FirmwareVersion = txb_Version.Text
                    _projectGeneratorService.NewDevice.IncludeFailsafe = ckb_IncludeFailsafe.Checked

                    result = True
                Else

                    If String.IsNullOrEmpty(txb_Station.Text) OrElse
                       String.IsNullOrEmpty(txb_DeviceName.Text) OrElse
                       String.IsNullOrEmpty(txb_OrderNr.Text) OrElse
                       String.IsNullOrEmpty(txb_Version.Text) Then
                        Throw New Exception("Error: The properties device name, station, order number and version are required!")
                    Else
                        _projectGeneratorService.NewDevice = New Device With {
                            .Station = txb_Station.Text,
                            .TemplateName = "custom edit",
                            .DeviceName = txb_DeviceName.Text,
                            .OrderNumber = txb_OrderNr.Text,
                            .FirmwareVersion = txb_Version.Text,
                            .IncludeFailsafe = ckb_IncludeFailsafe.Checked,
                            .PositionNumber = _projectGeneratorService.DeviceModel.CurrentDeviceCount
                        }

                        result = True
                    End If
                End If
            Catch e As Exception
                _traceWriter.Write(e.Message)
            End Try

            Return result
        End Function

#End Region

#Region "Compile"

        ''' <summary>
        ''' Set the current device if the selected item has been changed
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub cob_DeviceList_SelectedIndexChanged(sender As Object, e As EventArgs) Handles cob_DeviceList.SelectedIndexChanged
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            If cob_DeviceList.Items.Count > 0 Then
                _projectGeneratorService.SetCurrentDevice(CType(cob_DeviceList.SelectedItem, DeviceItem))
            End If
        End Sub

        ''' <summary>
        ''' Compile the selected device item
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub btn_CompileDevice_Click(sender As Object, e As EventArgs) Handles btn_CompileDevice.Click
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name)

            Cursor.Current = Cursors.WaitCursor

            Dim deviceItem = CType(cob_DeviceList.SelectedItem, DeviceItem)

            _projectGeneratorService.CompileDevice(deviceItem)

            Cursor.Current = Cursors.Default
        End Sub

#End Region

#End Region
    End Class
End Namespace
