Namespace Models
    Public Class Device
#Region "properties"

        Public Property Station As String

        Public Property TemplateName As String

        Public Property DeviceName As String

        Public Property OrderNumber As String

        Public Property FirmwareVersion As String

        Public Property IncludeFailsafe As Boolean

        Public Property PositionNumber As Integer

        Public ReadOnly Property TypeIdentifier As String
            Get
                Return "OrderNumber:" & OrderNumber & "/" & FirmwareVersion
            End Get
        End Property

        Public ReadOnly Property TypeName As String
            Get
                Return Station & "_" & (PositionNumber + 1).ToString()
            End Get
        End Property

        Public ReadOnly Property Name As String
            Get
                Return DeviceName
            End Get
        End Property

#End Region
    End Class
End Namespace
