Imports System.Collections.Generic

Namespace Models
    Public Class DisplayAutoLogoff
#Region "ctor"

        Public Sub New()
            AutoLogoffs = New List(Of AutoLogoff) From {
                New AutoLogoff With {.Name = "Disable", .Tag = "Disabled"},
                New AutoLogoff With {.Name = "1 minute", .Tag = "Value1Minute"},
                New AutoLogoff With {.Name = "2 minutes", .Tag = "Value2Minutes"},
                New AutoLogoff With {.Name = "5 minutes", .Tag = "Value5Minutes"},
                New AutoLogoff With {.Name = "10 minutes", .Tag = "Value10Minutes"},
                New AutoLogoff With {.Name = "15 minutes", .Tag = "Value15Minutes"},
                New AutoLogoff With {.Name = "30 minutes", .Tag = "Value30Minutes"},
                New AutoLogoff With {.Name = "1 hour", .Tag = "Value1Hour"}
            }
        End Sub

#End Region

#Region "properties"

        Public Property AutoLogoffs As List(Of AutoLogoff)

#End Region

#Region "methods"

        Public Function GetNamePropertyName() As String
            Return NameOf(AutoLogoff.Name)
        End Function

        Public Function GetTagPropertyName() As String
            Return NameOf(AutoLogoff.Tag)
        End Function

#End Region
    End Class
End Namespace
