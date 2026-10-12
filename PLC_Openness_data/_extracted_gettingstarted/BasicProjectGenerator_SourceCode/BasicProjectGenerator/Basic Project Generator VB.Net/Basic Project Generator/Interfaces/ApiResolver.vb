Imports System
Imports System.IO
Imports System.Reflection
Imports System.Security.AccessControl
Imports Microsoft.Win32

Namespace Interfaces
    Public Module ApiResolver
#Region "constants"

        Public Const Version = "V17"
        Private Const LibraryKey = "SOFTWARE\\Siemens\\Automation\\Openness\\17.0\\PublicAPI\\17.0.0.0"
        Private Const LibraryName = "Siemens.Engineering"

#End Region

#Region "methods"

        ''' <summary>
        ''' Determines the API library to be loaded 
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="args"></param>
        ''' <returns></returns>
        Public Function AssemblyResolver(sender As Object, args As ResolveEventArgs) As Assembly
            Dim lookupName = New AssemblyName(args.Name)
            If lookupName.Name.Equals(libraryName, StringComparison.OrdinalIgnoreCase) Then
                Dim libraryFilePath = GetLibraryFilePath()
                If Not String.IsNullOrWhiteSpace(libraryFilePath) Then
                    Dim suggestedName = AssemblyName.GetAssemblyName(libraryFilePath)
                    Return Assembly.Load(suggestedName)
                End If
            End If
            Return Nothing
        End Function

        ''' <summary>
        ''' Determines if the version of the API library is installed
        ''' </summary>
        ''' <returns></returns>
        Public Function IsOpennessInstalled() As Boolean
            Return Not String.IsNullOrWhiteSpace(GetLibraryFilePath())
        End Function

        Private Function GetLibraryFilePath() As String
            Using baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64)
                Using registryKey = baseKey.OpenSubKey(libraryKey, RegistryKeyPermissionCheck.ReadSubTree, RegistryRights.ReadKey)
                    Dim libraryFilePath = TryCast(registryKey?.GetValue(LibraryName), String)
                    If Not String.IsNullOrWhiteSpace(libraryFilePath) And File.Exists(libraryFilePath) Then
                        Return libraryFilePath
                    End If
                End Using
            End Using
            Return Nothing
        End Function

#End Region
    End Module
End Namespace
