Imports System
Imports System.IO
Imports System.Windows.Forms

Namespace UserInterfaces
    Public Class NewTiaPortalProject
#Region "fields"

        Private _folderBrowserDialog As FolderBrowserDialog

#End Region

#Region "ctor"

        Public Sub New()
            InitializeComponent()

            btn_Create.DialogResult = DialogResult.OK
            btn_Cancel.DialogResult = DialogResult.Cancel
            txb_ProjectName.Text = String.Empty
            ProjectName = String.Empty
            txb_Path.Text = String.Empty
            Path = String.Empty
            ProjectNameValidationError = False
            PathValidationError = False
        End Sub

#End Region

#Region "properties"

        Public Property ProjectName As String

        Public Property Path As String

        Public Property ProjectNameValidationError As Boolean

        Public Property PathValidationError As Boolean

        Public Property ExceptionOccurred As Boolean

#End Region

#Region "methods"

        ''' <summary>
        ''' Reset the validation error for the project name
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub ProjectName_TextChanged(sender As Object, e As EventArgs) Handles txb_ProjectName.TextChanged
            ProjectNameValidationError = False
        End Sub

        ''' <summary>
        ''' Open folder browser dialog for retrieve the target path
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub Path_Click(sender As Object, e As EventArgs) Handles btn_Path.Click
            Try
                _folderBrowserDialog = New FolderBrowserDialog()

                Dim result As DialogResult = _folderBrowserDialog.ShowDialog()
                If result = DialogResult.OK Then
                    txb_Path.Text = _folderBrowserDialog.SelectedPath
                End If
            Catch exception As Exception
                ExceptionOccurred = True
                MessageBox.Show(exception.Message, "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
            End Try
        End Sub

        ''' <summary>
        ''' Reset the validation error for the path
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub Path_TextChanged(sender As Object, e As EventArgs) Handles txb_Path.TextChanged
            PathValidationError = False
        End Sub

        ''' <summary>
        ''' Validation the input
        ''' </summary>
        Private Sub ValidationProvider()
            ExceptionOccurred = False
            Try
                ProjectNameValidationError = False
                ProjectName = txb_ProjectName.Text
                If String.IsNullOrEmpty(ProjectName) Then
                    ProjectNameValidationError = True
                End If
            Catch exception As Exception
                ExceptionOccurred = True
                MessageBox.Show(exception.Message, "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
            End Try

            Try
                PathValidationError = False
                Path = txb_Path.Text
                If String.IsNullOrEmpty(Path) OrElse Directory.Exists(Path) = False Then
                    PathValidationError = True
                End If
            Catch exception As Exception
                ExceptionOccurred = True
                MessageBox.Show(exception.Message, "Exception", MessageBoxButtons.OK, MessageBoxIcon.Error)
            End Try
        End Sub

        ''' <summary>
        ''' Validation the input and canceling close if an error occurred
        ''' </summary>
        ''' <paramname="sender"></param>
        ''' <paramname="e"></param>
        Private Sub NewTiaPortalProject_Closing(sender As Object, e As FormClosingEventArgs) Handles MyBase.FormClosing
            If DialogResult = DialogResult.OK Then
                ValidationProvider()

                If ProjectNameValidationError OrElse PathValidationError Then
                    e.Cancel = True
                    MessageBox.Show("Project name and valid path are both required!", "Validation Error", MessageBoxButtons.OK, MessageBoxIcon.Error)
                End If

                If ExceptionOccurred Then
                    e.Cancel = True
                End If
            End If
        End Sub

#End Region
    End Class
End Namespace
