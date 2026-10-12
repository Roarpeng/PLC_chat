Imports System.Drawing
Imports System.IO
Imports System.Text
Imports System.Text.RegularExpressions
Imports System.Windows.Forms
Imports Microsoft.VisualBasic

Namespace Interfaces
    Public Class TraceWriter
        Inherits TextWriter
#Region "fields"

        Private ReadOnly _list As ListBox
        Private _content As StringBuilder
        Private _maxHorizontalSize As Integer

#End Region

#Region "ctor"

        Public Sub New(list As ListBox)
            _content = new StringBuilder()
            _list = list
        End Sub

#End Region

#Region "properties"

        Public Overrides ReadOnly Property Encoding As Encoding
            Get
                Return Encoding.UTF8
            End Get
        End Property

#End Region

#Region "methods"

        ''' <summary>
        ''' Writes a log message to trace output
        ''' </summary>
        ''' <paramname="value"></param>
        Public Overrides Sub Write(value As String)
            MyBase.Write(value)

            Dim input = ReplaceSpecialCharacters(value)
            Dim timeStamp = Date.Now.ToString("yyyy-MM-dd HH:mm:ss.fff")
            _content.Append(timeStamp & vbTab & input)
            _list.Items.Add(_content.ToString())
            _list.SelectedIndex = _list.Items.Count - 1
            _content = New StringBuilder()

            DisplayHorizontalScroll()
        End Sub

        ''' <summary>
        ''' Activates the horizontal scroll bar if the message is too long for the trace output
        ''' </summary>
        Private Sub DisplayHorizontalScroll()
            _list.IntegralHeight = True
            _list.HorizontalScrollbar = True

            Dim graphics As Graphics = _list.CreateGraphics()

            Dim horizontalSize = CInt(graphics.MeasureString(_list.Items(_list.Items.Count - 1).ToString(), _list.Font).Width)

            If horizontalSize > _maxHorizontalSize Then
                _maxHorizontalSize = horizontalSize
            End If

            If _list IsNot Nothing Then _list.HorizontalExtent = _maxHorizontalSize
        End Sub

        ''' <summary>
        ''' Replace special characters with space
        ''' </summary>
        ''' <paramname="value"></param>
        ''' <returns></returns>
        Private Shared Function ReplaceSpecialCharacters(value As String) As String
            Dim result = Regex.Replace(value, "\n|\r|\t", " ")

            Return result
        End Function

#End Region
    End Class
End Namespace
