Imports System.Collections.Generic
Imports System.IO
Imports System.Xml.Linq
Imports System.Xml.Serialization

Namespace Models
    Public Class DeviceModel
#Region "properties"

        Public Property CurrentDeviceCount As Integer

        Public Property DeviceCatalog As Catalog

        Public Property DeviceItemComposition As IList(Of DeviceItem)

#End Region

#Region "methods"

        Public Sub LoadDeviceCatalog(catalogDocument As XDocument)
            InitDeviceCatalog()

            Dim serializer = New XmlSerializer(GetType(Catalog))

            If catalogDocument.Document IsNot Nothing Then
                Using stringReader = New StringReader(catalogDocument.Document.ToString())
                    DeviceCatalog = CType(serializer.Deserialize(stringReader), Catalog)
                End Using
            End If
        End Sub

        Private Sub InitDeviceCatalog()
            If DeviceCatalog IsNot Nothing AndAlso DeviceCatalog.DeviceItemComposition IsNot Nothing Then
                DeviceCatalog.DeviceItemComposition.Clear()
            End If
        End Sub

        Public Function GetNamePropertyName() As String
            Return NameOf(DeviceItem.Name)
        End Function

        Public Function GetDeviceNamePropertyName() As String
            Return NameOf(DeviceItem.DeviceName)
        End Function

#End Region
    End Class
End Namespace
