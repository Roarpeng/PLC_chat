Imports System
Imports System.Collections.Generic
Imports System.ComponentModel
Imports System.IO
Imports System.Linq
Imports System.Runtime.CompilerServices
Imports System.Security
Imports System.Windows.Forms
Imports Microsoft.VisualBasic
Imports Siemens.Engineering
Imports Siemens.Engineering.Compiler
Imports Siemens.Engineering.Hmi
Imports Siemens.Engineering.HW
Imports Siemens.Engineering.HW.Features
Imports Siemens.Engineering.SW

Namespace Interfaces
    Public Class ApiWrapper
        Implements INotifyPropertyChanged
#Region "fields"

        Private _tiaPortalProcessList As IList(Of TiaPortalProcess)
        Private ReadOnly _traceWriter As TraceWriter
        Private _tiaPortalMode As TiaPortalMode
        Public Event PropertyChanged As PropertyChangedEventHandler Implements INotifyPropertyChanged.PropertyChanged

#End Region

#Region "ctor"

        Public Sub New(traceWriter As TraceWriter, <CallerMemberName> Optional caller As String = "")
            _traceWriter = traceWriter
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            _traceWriter.Write(methodBase.Name & " called from " & caller & vbLf)
        End Sub

#End Region

#Region "properties"

        Public Property CurrentTiaPortalProcess As TiaPortalProcess

        Public Property TiaPortal As TiaPortal

        Public Property TiaPortalIsDisposed As Boolean

        Public Property IsModified As Boolean

        Public Property CurrentProject As Project

        Public Property AvailableProject As Project

        Public Property TiaPortalMode As TiaPortalMode
            Get
                Return _tiaPortalMode
            End Get
            Set
                If value <> _tiaPortalMode Then
                    _tiaPortalMode = value
                    NotifyPropertyChanged()
                End If
            End Set
        End Property

        Public Property Device As Device

#End Region

#Region "methods"

#Region "common"

        ''' <summary>
        ''' Notification of changes
        ''' </summary>
        ''' <paramname="propertyName"></param>
        Private Sub NotifyPropertyChanged(<CallerMemberName> Optional propertyName As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " " & propertyName)

            RaiseEvent PropertyChanged(Me, New PropertyChangedEventArgs(propertyName))
        End Sub

        ''' <summary>
        ''' Get the enum value to a string
        ''' </summary>
        ''' <typeparamname="T"></typeparam>
        ''' <paramname="value"></param>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetEnumValue(Of T As {Structure, IConvertible})(value As String, <CallerMemberName> Optional caller As String = "") As T
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            If Not GetType(T).IsEnum Then
                _traceWriter.Write("T must be an Enumeration type!")
                Throw New Exception("T must be an Enumeration type!")
            End If
            Dim enumValue = CType([Enum].GetValues(GetType(T)), T())(0)
            If Not String.IsNullOrEmpty(value) Then
                For Each itemValue In CType([Enum].GetValues(GetType(T)), T())

                    If itemValue.ToString(Nothing).ToUpper().Equals(value.ToUpper()) Then
                        enumValue = itemValue
                        Exit For
                    End If
                Next
            End If
            Return enumValue
        End Function

#End Region

#Region "TIA Portal"

        ''' <summary>
        ''' Open a TIA Portal instance
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub DoOpenTiaPortal(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            TiaPortal = New TiaPortal(TiaPortalMode)
            TiaPortalIsDisposed = False
        End Sub

        ''' <summary>
        ''' Connect to a open TIA Portal instance
        ''' </summary>
        ''' <paramname="processId"></param>
        ''' <paramname="caller"></param>
        Public Sub DoConnectTiaPortal(processId As Integer, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim portal = TiaPortal.GetProcess(processId, 5000).Attach()

            If portal IsNot Nothing Then
                TiaPortal?.Dispose()
                TiaPortalIsDisposed = True
                CurrentProject = Nothing
                TiaPortal = portal
                TiaPortalIsDisposed = False
            End If
        End Sub

        ''' <summary>
        ''' Close a TIA Portal instance
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub DoCloseTiaPortal(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            TiaPortal.GetCurrentProcess().Dispose()
            TiaPortalIsDisposed = True
            CurrentProject = Nothing
        End Sub

        ''' <summary>
        ''' Get all TIA Portal processes on the local machine
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function DoGetTiaPortalProcesses(<CallerMemberName> Optional caller As String = "") As IList(Of String)
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim processIds As IList(Of String) = Nothing
            CurrentTiaPortalProcess = TiaPortal?.GetCurrentProcess()
            _tiaPortalProcessList = New List(Of TiaPortalProcess)()
            _tiaPortalProcessList = TiaPortal.GetProcesses()
            If _tiaPortalProcessList.Count > 0 Then
                processIds = New List(Of String)()
                For Each item In _tiaPortalProcessList
                    Dim mode = If(item.Mode = TiaPortalMode.WithoutUserInterface, " Without UI", " With UI")
                    processIds.Add($"ID {item.Id} {vbTab} {mode}")
                Next
            End If
            Return processIds
        End Function

        ''' <summary>
        ''' Get the current process id
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function DoGetCurrentTiaProcessId(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Return If(CurrentTiaPortalProcess IsNot Nothing, CurrentTiaPortalProcess.Id.ToString(), String.Empty)
        End Function

#End Region

#Region "TIA Portal Project"

        ''' <summary>
        ''' Create a new project
        ''' </summary>
        ''' <paramname="projectModel"></param>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function DoCreateNewProject(projectModel As Models.ProjectModel, <CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = False
            DoCloseProject()
            Dim newProject = TiaPortal.Projects.Create(projectModel.TargetDirectory, projectModel.Name)
            _traceWriter.Write($"TiaPortal.Projects.Create({projectModel.TargetDirectory.FullName}, {projectModel.Name}")
            If newProject IsNot Nothing Then
                CurrentProject = newProject
                result = True
            End If
            Return result
        End Function

        ''' <summary>
        ''' Open a project
        ''' </summary>
        ''' <paramname="path"></param>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function DoOpenProject(path As String, <CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim processId = -1
            Dim result = False
            Dim loadOpenProject = False
            Dim accessGranted = True
            DoCloseProject()
            _tiaPortalProcessList = New List(Of TiaPortalProcess)()
            _tiaPortalProcessList = TiaPortal.GetProcesses()
            If _tiaPortalProcessList.Count > 0 Then
                For Each item In _tiaPortalProcessList
                    If item.ProjectPath IsNot Nothing AndAlso Equals(item.ProjectPath.FullName, path) Then
                        processId = item.Id
                        accessGranted = False
                        loadOpenProject = True
                        If MessageBox.Show("Do you want to connect to the instance (process: " & processId & ")?", "The project is already open", MessageBoxButtons.YesNo, MessageBoxIcon.Question) = DialogResult.Yes Then
                            accessGranted = True
                        End If
                        Exit For
                    End If
                Next
            End If
            If Not loadOpenProject Then
                Dim newProject As Project = TiaPortal.Projects.Open(New FileInfo(path))
                _traceWriter.Write($"TiaPortal.Projects.Open({path}")
                If newProject IsNot Nothing Then
                    CurrentProject = newProject
                    result = True
                End If
            End If
            If loadOpenProject AndAlso accessGranted AndAlso processId <> -1 Then
                DoConnectTiaPortal(processId)
                DoLoadProject()
                result = True
            End If
            Return result
        End Function

        ''' <summary>
        ''' Load a project from connected instance -> see 'DoConnectTiaPortal'
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub DoLoadProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            CurrentProject = TiaPortal.Projects.FirstOrDefault()
        End Sub

        ''' <summary>
        ''' Save changes to a project
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub DoSaveProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            CurrentProject.Save()
        End Sub

        ''' <summary>
        ''' Closes the first and only open project of the connected TIA portal instance 
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub DoCloseProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            If Not TiaPortalIsDisposed AndAlso TiaPortal?.Projects.Count > 0 Then
                Dim project = TiaPortal.Projects.FirstOrDefault()
                project?.Close()
            End If
            CurrentProject = Nothing
        End Sub

#End Region

#Region "Device"

        ''' <summary>
        ''' Get the list of devices in the loaded project
        ''' </summary>
        ''' <paramname="deviceModel"></param>
        ''' <paramname="caller"></param>
        Public Sub GetCurrentDeviceList(deviceModel As Models.DeviceModel, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            For Each feDevice In CurrentProject.Devices
                Dim deviceItemComposition = feDevice.DeviceItems
                For Each deviceItem In deviceItemComposition
                    If deviceItem.Classification = DeviceItemClassifications.CPU Then
                        Dim newItem = New Models.DeviceItem With {
                            .Name = deviceItem.Name,
                            .DeviceName = feDevice.Name,
                            .Classification = deviceItem.Classification.ToString()
                        }
                        deviceModel.DeviceItemComposition.Add(newItem)
                    End If
                Next
            Next
        End Sub

        ''' <summary>
        ''' Set the selected deviceItem as the current device
        ''' </summary>
        ''' <paramname="deviceItem"></param>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function SetCurrentDevice(deviceItem As Models.DeviceItem, <CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = False
            For Each feDevice In CurrentProject.Devices

                If Equals(feDevice.Name, deviceItem.DeviceName) Then
                    Dim deviceItemComposition = feDevice.DeviceItems
                    For Each item In deviceItemComposition
                        If Equals(item.Name, deviceItem.Name) Then
                            Device = feDevice
                            result = True
                        End If
                    Next
                End If
            Next
            Return result
        End Function

        ''' <summary>
        ''' Add a new device based on device template
        ''' </summary>
        ''' <paramname="typeIdentifier"></param>
        ''' <paramname="name"></param>
        ''' <paramname="deviceName"></param>
        ''' <paramname="caller"></param>
        Public Sub DoAddNewDevice(typeIdentifier As String, name As String, deviceName As String, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Device = CurrentProject.Devices.CreateWithItem(typeIdentifier, name, deviceName)
            IsModified = CurrentProject.IsModified
        End Sub

        ''' <summary>
        ''' Set PLC security settings
        ''' </summary>
        ''' <paramname="deviceName"></param>
        ''' <paramname="includeFailsafe"></param>
        ''' <paramname="protectConfiguration"></param>
        ''' <paramname="accessLevel"></param>
        ''' <paramname="masterSecretPassword"></param>
        ''' <paramname="accessLevelPassword"></param>
        ''' <paramname="caller"></param>
        Public Sub DoSetPlcSecuritySettings(deviceName As String, includeFailsafe As Boolean, protectConfiguration As Boolean, accessLevel As String, masterSecretPassword As SecureString, accessLevelPassword As SecureString, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim accessLevelValue = GetEnumValue(Of PlcProtectionAccessLevel)(accessLevel)
            If protectConfiguration Then
                SetPlcMasterSecretConfiguration(deviceName, masterSecretPassword)
            End If
            SetPlcProtectionAccessLevel(deviceName, includeFailsafe, accessLevelValue, accessLevelPassword)
        End Sub

        ''' <summary>
        ''' Set PLC protection settings
        ''' </summary>
        ''' <paramname="deviceName"></param>
        ''' <paramname="password"></param>
        ''' <paramname="caller"></param>
        Private Sub SetPlcMasterSecretConfiguration(deviceName As String, password As SecureString, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim deviceItemComposition = Device.DeviceItems
            For Each deviceItem In deviceItemComposition
                If Equals(deviceItem.Name, deviceName) OrElse Equals(Device.Name, deviceName) Then
                    Dim plcMasterSecretConfigurator = deviceItem.GetService(Of PlcMasterSecretConfigurator)()
                    plcMasterSecretConfigurator?.Protect(password)
                End If
            Next
        End Sub

        ''' <summary>
        ''' Set PLC protection access level
        ''' </summary>
        ''' <paramname="deviceName"></param>
        ''' <paramname="includeFailsafe"></param>
        ''' <paramname="accessLevel"></param>
        ''' <paramname="password"></param>
        ''' <paramname="caller"></param>
        Private Sub SetPlcProtectionAccessLevel(deviceName As String, includeFailsafe As Boolean, accessLevel As PlcProtectionAccessLevel, password As SecureString, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim deviceItemComposition = Device.DeviceItems
            For Each deviceItem In deviceItemComposition

                If Equals(deviceItem.Name, deviceName) OrElse Equals(Device.Name, deviceName) Then
                    Dim plcAccessLevelProvider = deviceItem.GetService(Of PlcAccessLevelProvider)()
                    If plcAccessLevelProvider IsNot Nothing Then
                        If accessLevel = PlcProtectionAccessLevel.FullAccess Then
                            plcAccessLevelProvider.PlcProtectionAccessLevel = accessLevel
                        Else
                            plcAccessLevelProvider.PlcProtectionAccessLevel = accessLevel
                            If includeFailsafe Then
                                plcAccessLevelProvider.SetPassword(PlcProtectionAccessLevel.FullAccessIncludingFailsafe, password)
                            Else
                                plcAccessLevelProvider.SetPassword(PlcProtectionAccessLevel.FullAccess, password)
                            End If
                        End If
                    End If
                End If
            Next
        End Sub

        ''' <summary>
        ''' Set display protection settings
        ''' </summary>
        ''' <paramname="deviceName"></param>
        ''' <paramname="displayProtection"></param>
        ''' <paramname="timeUntilDisplayAutoLogoff"></param>
        ''' <paramname="displayProtectionPassword"></param>
        ''' <paramname="caller"></param>
        Public Sub DoSetDisplayProtection(deviceName As String, displayProtection As Boolean, timeUntilDisplayAutoLogoff As String, displayProtectionPassword As SecureString, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim deviceItemComposition = Device.DeviceItems
            For Each deviceItem In deviceItemComposition
                If Equals(deviceItem.Name, deviceName) OrElse Equals(Device.Name, deviceName) Then
                    Dim items = deviceItem.DeviceItems
                    If items IsNot Nothing AndAlso items.Count > 0 Then
                        For Each item In items
                            Dim displayProtectionService = item.GetService(Of DisplayProtection)()
                            If displayProtectionService IsNot Nothing Then
                                If displayProtection Then
                                    Dim displayAutoLogOffTime = GetEnumValue(Of DisplayAutoLogOffTime)(timeUntilDisplayAutoLogoff)
                                    displayProtectionService.SetAttribute("DisplayProtection", true)
                                    displayProtectionService.SetAttribute("DisplayAutoLogOffTime", displayAutoLogOffTime)
                                    displayProtectionService.SetPassword(displayProtectionPassword)
                                Else
                                    displayProtectionService.SetAttribute("DisplayProtection", false)
                                End If
                                Exit For
                            End If
                        Next
                    End If
                End If
            Next
        End Sub

#End Region

#Region "Compile"

        ''' <summary>
        ''' Compile a device
        ''' </summary>
        ''' <paramname="deviceItem"></param>
        ''' <paramname="caller"></param>
        Public Sub DoCompileDevice(deviceItem As Models.DeviceItem, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim deviceNotFound = True
            For Each feDevice In CurrentProject.Devices
                If Equals(feDevice.Name, deviceItem.DeviceName) Then
                    Dim deviceItemComposition = feDevice.DeviceItems
                    For Each item In deviceItemComposition
                        If Equals(item.Name, deviceItem.Name) Then
                            Dim softwareContainer = item.GetService(Of SoftwareContainer)()
                            If softwareContainer IsNot Nothing Then
                                If TypeOf softwareContainer.Software Is PlcSoftware Then
                                    Dim controllerTarget = TryCast(softwareContainer.Software, PlcSoftware)
                                    If controllerTarget IsNot Nothing Then
                                        deviceNotFound = False
                                        Dim plcCompiler = controllerTarget.GetService(Of ICompilable)()
                                        Dim plcCompilerResult As CompilerResult = plcCompiler.Compile()
                                        Dim compilerMessage = "Compiling Software of " & deviceItem.DeviceName & " - " & deviceItem.Name
                                        _traceWriter.Write(compilerMessage)
                                        If plcCompilerResult.Messages.Count > 0 Then
                                            If plcCompilerResult.Messages IsNot Nothing AndAlso plcCompilerResult.Messages.Count > 0 Then
                                                GetCompilerMessages("", plcCompilerResult.Messages)
                                            End If
                                        End If
                                    End If
                                End If
                                If TypeOf softwareContainer.Software Is HmiTarget Then
                                    Dim hmiTarget = TryCast(softwareContainer.Software, HmiTarget)
                                    If hmiTarget IsNot Nothing Then
                                        deviceNotFound = False
                                        Dim hmiCompiler = hmiTarget.GetService(Of ICompilable)()
                                        Dim hmiCompilerResult As CompilerResult = hmiCompiler.Compile()
                                        Dim compilerMessage = "Compiling HMI of " & deviceItem.DeviceName & " - " & deviceItem.Name
                                        _traceWriter.Write(compilerMessage)
                                        If hmiCompilerResult.Messages.Count > 0 Then
                                            If hmiCompilerResult.Messages IsNot Nothing AndAlso hmiCompilerResult.Messages.Count > 0 Then
                                                GetCompilerMessages("", hmiCompilerResult.Messages)
                                            End If
                                        End If
                                    End If
                                End If
                            End If
                            Dim compileProvider = item.GetService(Of ICompilable)()
                            If compileProvider IsNot Nothing Then
                                deviceNotFound = False
                                Dim compileResult As CompilerResult = compileProvider.Compile()
                                Dim compilerMessage = "Compiling Hardware of " & deviceItem.DeviceName & " - " & deviceItem.Name
                                _traceWriter.Write(compilerMessage)
                                If compileResult.Messages.Count > 0 Then
                                    If compileResult.Messages IsNot Nothing AndAlso compileResult.Messages.Count > 0 Then
                                        GetCompilerMessages("", compileResult.Messages)
                                    End If
                                End If
                            End If
                        End If
                    Next
                End If
            Next
            If deviceNotFound Then
                _traceWriter.Write("No device found to compile!")
            End If
        End Sub

        ''' <summary>
        ''' Retrieve recursive the compile messages
        ''' </summary>
        ''' <paramname="path"></param>
        ''' <paramname="messageComposition"></param>
        Private Sub GetCompilerMessages(path As String, messageComposition As CompilerResultMessageComposition)
            For Each message In messageComposition
                If message.Messages IsNot Nothing AndAlso message.Messages.Count > 0 Then
                    GetCompilerMessages(message.Path, message.Messages)
                End If
                If Not String.IsNullOrWhiteSpace(path) AndAlso Not String.IsNullOrWhiteSpace(message.Description) Then
                    Dim compilerMessage = "Path: " & path & " / State: " & message.State & " / Description: " & message.Description
                    _traceWriter.Write(compilerMessage)
                End If
                If String.IsNullOrWhiteSpace(path) AndAlso Not String.IsNullOrWhiteSpace(message.Description) Then
                    Dim compilerMessage = "State: " & message.State & " / Description: " & message.Description
                    _traceWriter.Write(compilerMessage)
                End If
            Next
        End Sub

#End Region

#End Region
    End Class
End Namespace
