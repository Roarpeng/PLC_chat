Imports System
Imports System.Collections.Generic
Imports System.IO
Imports System.Linq
Imports System.Runtime.CompilerServices
Imports System.Windows.Forms
Imports System.Xml.Linq
Imports Basic_Project_Generator.Interfaces
Imports Basic_Project_Generator.Models
Imports Basic_Project_Generator.UserInterfaces

Namespace Services
    Public Class ProjectGeneratorService
#Region "fields"

        Private ReadOnly _traceWriter As TraceWriter
        Private ReadOnly _apiWrapper As ApiWrapper

#End Region

#Region "ctor"

        Public Sub New(traceWriter As TraceWriter, apiWrapper As ApiWrapper)
            _traceWriter = traceWriter
            _apiWrapper = apiWrapper
            NewProject = New ProjectModel()
            DeviceModel = New DeviceModel With {
                .DeviceItemComposition = New List(Of DeviceItem)()
            }
            SelectedProcessIndex = -1
            NewDevice = Nothing
        End Sub

#End Region

#Region "properties"

        Public Property NewProject As ProjectModel

        Public Property SelectedProcessIndex As Integer

        Public Property SelectedProcessItem As String

        Public Property SelectedProject As String

        Public Property DeviceCatalogXml As XDocument

        Public Property DeviceModel As DeviceModel

        Public Property DeviceCatalogLoaded As Boolean

        Public Property NewDevice As Device

#End Region

#Region "methods"

#Region "TIA Portal"

        ''' <summary>
        ''' Open a TIA Portal instance
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub OpenTiaPortal(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoOpenTiaPortal()
        End Sub

        ''' <summary>
        ''' Connect to a open TIA Portal instance
        ''' </summary>
        ''' <paramname="processId"></param>
        ''' <paramname="caller"></param>
        Public Sub ConnectTiaPortal(processId As Integer, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoConnectTiaPortal(processId)
        End Sub

        ''' <summary>
        ''' Close a TIA Portal instance
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub CloseTiaPortal(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoCloseTiaPortal()
        End Sub

        ''' <summary>
        ''' Retrieve the current process id
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetCurrentTiaProcessId(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Return _apiWrapper.DoGetCurrentTiaProcessId()
        End Function

        ''' <summary>
        ''' Get all TIA Portal processes on the local machine
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetTiaPortalProcesses(<CallerMemberName> Optional caller As String = "") As IList(Of String)
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Return _apiWrapper.DoGetTiaPortalProcesses()
        End Function

        ''' <summary>
        ''' Extract the process id from selected item and convert to int value
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetSelectedProcessId(<CallerMemberName> Optional caller As String = "") As Integer
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim id = -1
            If SelectedProcessIndex > -1 Then
                id = Convert.ToInt32(SelectedProcessItem.Split(" "c)(1))
            End If
            Return id
        End Function

        ''' <summary>
        ''' Extract the process id from selected item and get it as string
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetSelectedProcessIdAsString(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim processId = String.Empty
            If GetSelectedProcessId() > -1 Then
                processId = GetSelectedProcessId().ToString()
            End If
            Return processId
        End Function

#End Region

#Region "TIA Portal Project"

        ''' <summary>
        ''' Retrieve the current project name
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetCurrentProjectName(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Return If(_apiWrapper.CurrentProject IsNot Nothing, _apiWrapper.CurrentProject.Name, String.Empty)
        End Function

        ''' <summary>
        ''' Retrieve the current project target directory
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetTargetDirectory(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Return If(_apiWrapper.CurrentProject IsNot Nothing, _apiWrapper.CurrentProject.Path.DirectoryName, String.Empty)
        End Function

        ''' <summary>
        ''' Retrieve the available project from TIA Portal instance
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function GetAvailableProject(<CallerMemberName> Optional caller As String = "") As String
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim availableProject = String.Empty
            If _apiWrapper.TiaPortal IsNot Nothing AndAlso _apiWrapper.TiaPortalIsDisposed = False Then
                _apiWrapper.AvailableProject = _apiWrapper.TiaPortal.Projects.FirstOrDefault()

                If _apiWrapper.AvailableProject IsNot Nothing Then
                    availableProject = _apiWrapper.AvailableProject.Name
                End If
            End If
            Return availableProject
        End Function

        ''' <summary>
        ''' Create a new project
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function CreateNewProject(<CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = False
            Dim newTiaPortalProject = New NewTiaPortalProject()
            If DialogResult.OK = newTiaPortalProject.ShowDialog() Then
                NewProject.Name = newTiaPortalProject.ProjectName
                NewProject.TargetDirectory = New DirectoryInfo(newTiaPortalProject.Path)
                If _apiWrapper.DoCreateNewProject(NewProject) Then
                    result = True
                End If
            End If
            Return result
        End Function

        ''' <summary>
        ''' Open a selected project
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function OpenProject(<CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = False
            If SelectProject() Then
                If _apiWrapper.DoOpenProject(SelectedProject) Then
                    result = True
                End If
            End If
            Return result
        End Function

        ''' <summary>
        ''' Open a file dialog and retrieve all *.ap* files to select a project file
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Private Function SelectProject(<CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = False
            SelectedProject = String.Empty
            Dim fileSearch = New OpenFileDialog With {
                .Filter = "TIA Portal projects|*.ap*",
                .RestoreDirectory = True
            }
            If DialogResult.OK = fileSearch.ShowDialog() Then
                SelectedProject = fileSearch.FileName
                result = True
            End If
            Return result
        End Function

        ''' <summary>
        ''' Load a open project from connected instance -> see 'DoConnectTiaPortal'
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub LoadProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoLoadProject()
        End Sub

        ''' <summary>
        ''' Save changes to a project
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub SaveProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoSaveProject()
        End Sub

        ''' <summary>
        ''' Close a project
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub CloseProject(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoCloseProject()
        End Sub

        ''' <summary>
        ''' Retrieve the device list from current project
        ''' </summary>
        ''' <paramname="caller"></param>
        Public Sub GetCurrentDeviceList(<CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            DeviceModel.DeviceItemComposition.Clear()
            _apiWrapper.GetCurrentDeviceList(DeviceModel)
        End Sub

        ''' <summary>
        ''' Set the selected deviceItem as the current device 
        ''' </summary>
        ''' <paramname="deviceItem"></param>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function SetCurrentDevice(deviceItem As DeviceItem, <CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim result = _apiWrapper.SetCurrentDevice(deviceItem)
            If Not result Then
                _traceWriter.Write("No device found!")
            Else
                _traceWriter.Write("Device found: " & deviceItem.DeviceName)
            End If
            Return result
        End Function

#End Region

#Region "Device"

        ''' <summary>
        ''' Load the template catalog for new devices from xml.
        ''' If th catalog is changed, the current project should be close and reopened
        ''' to reload the catalog changes.
        ''' </summary>
        ''' <paramname="caller"></param>
        ''' <returns></returns>
        Public Function LoadDeviceCatalog(<CallerMemberName> Optional caller As String = "") As Boolean
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            DeviceCatalogLoaded = False
            DeviceCatalogXml = XDocument.Load("Assets\DeviceCatalog.xml")
            DeviceModel.LoadDeviceCatalog(DeviceCatalogXml)
            DeviceCatalogLoaded = True
            Return DeviceCatalogLoaded
        End Function

        ''' <summary>
        ''' Add a new device to a project
        ''' </summary>
        ''' <paramname="device"></param>
        ''' <paramname="caller"></param>
        Public Sub AddNewDevice(device As Device, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoAddNewDevice(device.TypeIdentifier, device.Name, device.TypeName)
        End Sub

        ''' <summary>
        ''' Set PLC Security settings.
        ''' The Security settings dialog will be opened for entering the security configuration.
        ''' </summary>
        ''' <paramname="deviceName"></param>
        ''' <paramname="includeFailsafe"></param>
        ''' <paramname="caller"></param>
        Public Sub SetPlcSecuritySettings(deviceName As String, includeFailsafe As Boolean, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            Dim plcSecuritySettings = New PlcSecuritySettings With {
                .IncludeFailsafe = includeFailsafe
            }
            If DialogResult.OK = plcSecuritySettings.ShowDialog() Then
                Dim protectPlcConfiguration = plcSecuritySettings.ProtectPlcConfiguration
                Dim masterSecretPassword = plcSecuritySettings.MasterSecretPassword
                Dim accessLevelPassword = plcSecuritySettings.AccessLevelPassword
                Dim accessLevel = plcSecuritySettings.AccessLevel
                Dim displayProtection = plcSecuritySettings.DisplayProtection
                Dim displayProtectionPassword = plcSecuritySettings.DisplayProtectionPassword
                Dim timeUntilDisplayAutoLogoff = plcSecuritySettings.TimeUntilDisplayAutoLogoff

                _apiWrapper.DoSetPlcSecuritySettings(deviceName, includeFailsafe, protectPlcConfiguration, accessLevel, masterSecretPassword, accessLevelPassword)
                _apiWrapper.DoSetDisplayProtection(deviceName, displayProtection, timeUntilDisplayAutoLogoff, displayProtectionPassword)
            End If
        End Sub

#End Region

#Region "Compile"

        ''' <summary>
        ''' Compile a selected device item
        ''' </summary>
        ''' <paramname="deviceItem"></param>
        ''' <paramname="caller"></param>
        Public Sub CompileDevice(deviceItem As DeviceItem, <CallerMemberName> Optional caller As String = "")
            Dim methodBase = Reflection.MethodBase.GetCurrentMethod()
            If methodBase.ReflectedType IsNot Nothing Then _traceWriter.Write(methodBase.ReflectedType.Name & "." & methodBase.Name & " called from " & caller)

            _apiWrapper.DoCompileDevice(deviceItem)
        End Sub

#End Region

#End Region
    End Class
End Namespace
